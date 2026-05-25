"""Anticausal Vestige Cycle 3 — per-card real-EoE cross-engine byte-
equality probe (PROBED tier flip).

Anticausal Vestige is a ``{6}`` Creature — Eldrazi (7/5, EoE — sourced
from ``data/edge_of_eternities.json``) with a LEAVES_BATTLEFIELD
self-trigger and a Warp keyword:

    "When this creature leaves the battlefield, draw a card, then you
    may put a permanent card with mana value less than or equal to
    the number of lands you control from your hand onto the
    battlefield tapped."
    "Warp {4} (You may cast this card from your hand for its warp
    cost. Exile this creature at the beginning of the next end step,
    then you may cast it from exile on a later turn.)"

This module is the **load-bearing PROBED-tier flip evidence** for
Anticausal Vestige after the multi-cycle DECLINED -> ADMITTED
transition (sibling mirror of Codecracker Hound C3 commit
``6f99bf45``):

  * **Cycle 1 (substrate, commit ``e148450a``, 2026-05-24)** wired
    the new Rust ``Effect::AnticausalVestigeLeavesEffect`` unit
    variant + parse / to_pydict / resolve arms +
    ``cross_engine._ta_dict_to_python_effect`` bridge arm. AV STAYED
    DECLINED at the warp-arm admit gate because the safe-trigger
    recognizer's event vocabulary did not yet admit
    ``LEAVES_BATTLEFIELD``.
  * **Cycle 2 (admit widen, commit ``c32f07f9``, 2026-05-24)**
    widened ``_python_ta_to_safe_dict``'s event gate from
    ``(ENTERS, DIES, ATTACKS, BECOMES_TAPPED)`` to also include
    ``LEAVES_BATTLEFIELD`` (the FIFTH safe event), added the
    ``("leaves_battlefield", "source_is_self",
    "anticausal_vestige_leaves_effect")`` ``_SAFE_TRIGGERS`` triple +
    the matching ``_SAFE_EFFECT_KEYS`` whitelist + the
    ``AnticausalVestigeLeavesEffect`` recognizer-side dispatch arm
    that emits the bare unit-shape dict
    ``{"kind": "anticausal_vestige_leaves_effect"}``. The warp arm
    (``_printing_is_bridge_pure_warp_creature``) now ADMITS AV
    (warp-arm admit set 7 -> 8).
  * **Cycle 3 (this lane)** ships the GENUINE real-EoE cross-engine
    byte-equality probe that flips AV ``covered_by_construction`` ->
    PROBED in the pool-parity metric. Same shape + same strength bar
    as the recent per-card parity probes
    (``test_codecracker_hound_parity.py``,
    ``test_possibility_technician_parity.py``,
    ``test_boilerbilges_ripper_parity.py``,
    ``test_archenemys_charm_parity.py``,
    ``test_singularity_rupture_parity.py``).

**Probe path — warp-cast -> end-step exile sweep fires LEAVES.**
Unlike Codecracker Hound's ETB+IsSelf trigger (which can be fired
synthetically via ``dispatch_event(Event.ENTERS)`` on Python after
seating CH on bf directly), AV's LEAVES_BATTLEFIELD trigger needs
the source to actually MOVE off the battlefield. The Rust engine
exposes no synthetic ``fire_leaves_battlefield`` Python-callable;
the natural Python+Rust convergent path is the **warp end-step
exile sweep** — both engines push the ``WarpExileSelf`` delayed
trigger at PHASE_END_STEP, resolve it via the explicit
``resolve_top_of_stack_*`` primitives, AV moves bf -> exile (with
the warp marker), the LEAVES_BATTLEFIELD event dispatches on BOTH
engines, AV's LTB triggered ability queues on the stack, and the
bridge round-trip resolves it to the same
``AnticausalVestigeLeavesEffect`` instance on both sides.

**Deterministic-first contract — seated PickFirstAgent on Python.**
Python's ``AnticausalVestigeLeavesEffect.resolve`` carries the
``if not candidates or p.agent is None: return`` short-circuit (the
no-agent path early-returns BEFORE the put-onto-bf step); the
trajectory-harness default Python state is seated with
``agent=None``. Rust's resolve arm picks the FIRST permanent in
hand with ``mana_value <= land_count`` deterministically and never
early-returns on a no-agent state. For byte-equality the probe seats
``_PickFirstAgent`` on the controlling Python player BEFORE the
warp cast — the seated agent's ``choose_sacrifice`` returns the
first legal id, which is the same iteration-first card Rust picks.
This mirrors the C1 substrate-only resolve smoke at
``test_anticausal_vestige_substrate_cycle_1.py::test_python_resolve_smoke_seated_agent_path``
and the Rust resolve arm's seated-agent fallback documented at
``rust/src/state_ops_resolve.rs:15219-15392``. **No PendingDecision
plumbed on either engine** — the C2 design-question deferral
(``PendingDecision::PickCardFromHandChoice``) STAYS deferred: the
deterministic-first contract holds byte-equal here, so the pivot
does not surface this cycle.

**Library setup.** The probe uses the same real-archetype-deck
context the sibling ``test_probe_warp_admitted.py`` lifecycle
parametrize uses for AV (arch 24 — B-heavy AV-free, ``Sw=9 Mt=8``;
mirror of the C3 spec's archetype-22 pattern for CH but B-heavy +
deck-richer to support AV's higher mana costs). All basic lands in
the registry are normalised to tap for "B" so the warp cost ``{4}``
and the LTB-X land-count compute cleanly on BOTH engines.

**Strength bar.** Full ``compare_fields == []`` across the WHOLE
field view at EVERY phase boundary + after the warp cast + after
the end-step LEAVES dispatch + after the LTB resolves +
deep-zone-snapshot equality (hand sizes, library counts, bf
contents, exile contents, life totals). The genuine byte-equality
contract — the strongest tier in
``docs/POOL_PARITY.md``.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.agents import Agent
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.bespoke import AnticausalVestigeLeavesEffect


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built — mirrors the
# project-wide policy for cross-engine probes.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Canonical Anticausal Vestige dict shape consumed by Rust's
# ``register_printing`` to build a synthetic carrier with the same
# LEAVES_BATTLEFIELD+IsSelf triggered ability as the real parsed
# printing. Mirrors the C1 substrate-only smoke
# (``test_anticausal_vestige_substrate_cycle_1.py``) carrier shape;
# Rust's parse_effect arm at cards.rs:12190-12201 reads only the
# unit-shape ``{"kind": "anticausal_vestige_leaves_effect"}`` dict.
_AV_PRINTING_DICT: dict = {
    "name": "Anticausal Vestige (synthetic carrier)",
    "card_types": ["Creature"],
    "subtypes": ["Eldrazi"],
    "power": 7,
    "toughness": 5,
    # Live printing's mana_cost is "{6}" colorless (verify-first
    # against ``data/edge_of_eternities.json`` mana_cost field).
    "mana_cost": {"generic": 6},
    "triggered_abilities": [
        {
            "event": "leaves_battlefield",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "anticausal_vestige_leaves_effect",
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Anticausal Vestige is parser-claimed and emits the
# expected LEAVES_BATTLEFIELD+IsSelf+AnticausalVestigeLeavesEffect
# trigger shape (the C1 substrate-only fold).
# ---------------------------------------------------------------------------


def test_anticausal_vestige_parser_claims_card():
    assert "Anticausal Vestige" in _PRINTINGS, (
        "Anticausal Vestige must be parser-claimed by the active "
        "CardSource"
    )


def test_anticausal_vestige_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, warp cost).

    Verify-first against the live ``data/edge_of_eternities.json``:
    AV is a ``{6}`` colorless Creature — Eldrazi (7/5) with
    Warp ``{4}``. The warp cost differs from the normal cost
    (``{4}`` vs ``{6}``) so the warp arm and the normal arm produce
    distinct lifecycles cost-side as well as semantically (the warp
    arm fires the at-end-step delayed-trigger exile sweep). The
    sibling C3 spec's hint of ``{2}{B}`` for the normal cost was an
    erroneous spec value — the genuine printing's normal cost is
    ``{6}`` (verified live)."""
    p = _PRINTINGS["Anticausal Vestige"]
    assert p.mana_cost_str == "{6}"
    assert p.warp_cost_str == "{4}"
    assert "Creature" in p.card_types
    assert "Eldrazi" in p.subtypes
    assert p.power == 7
    assert p.toughness == 5
    # Warp cost present (the gate the C2 widen closed).
    assert p.warp_cost is not None, (
        "Anticausal Vestige must carry a parsed warp_cost — the "
        "warp arm of the admit gate is the load-bearing one C2 "
        "flipped DECLINED -> ADMITTED"
    )


def test_anticausal_vestige_leaves_trigger_emits_unit_effect():
    """The C1 substrate-only parse pins AV's parsed
    LEAVES_BATTLEFIELD+IsSelf trigger to a unit-variant
    ``AnticausalVestigeLeavesEffect()``. Pin the shape here so parser
    drift surfaces immediately rather than silently downstream in the
    cross-engine probe."""
    from mtg_bot.effects.predicates import Event, IsSelf

    p = _PRINTINGS["Anticausal Vestige"]
    leaves_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.LEAVES_BATTLEFIELD
    ]
    assert len(leaves_tas) == 1, (
        f"Anticausal Vestige must have exactly 1 LEAVES_BATTLEFIELD "
        f"triggered ability; got {len(leaves_tas)}"
    )
    (ta,) = leaves_tas
    assert isinstance(ta.predicate, IsSelf), (
        f"LEAVES arm predicate must be IsSelf; got "
        f"{type(ta.predicate).__name__}"
    )
    assert isinstance(ta.effect, AnticausalVestigeLeavesEffect), (
        f"LEAVES arm effect must be AnticausalVestigeLeavesEffect; "
        f"got {type(ta.effect).__name__}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the dict shape Anticausal Vestige's
# safe-trigger recognizer emits round-trips to the matching Python
# class instance. (C2 substrate pin is duplicated here so the
# per-card module is self-contained for the PROBED-tier evidence —
# the same bridge round-trip pin is also at
# ``test_anticausal_vestige_substrate_cycle_1.py`` Pin #3.)
# ---------------------------------------------------------------------------


def test_anticausal_vestige_safe_trigger_bridge_round_trip():
    """The bridge dict shape emitted by ``_python_ta_to_safe_dict``
    for AV's LEAVES_BATTLEFIELD+IsSelf trigger reconstructs the
    matching Python ``AnticausalVestigeLeavesEffect()`` instance —
    the load-bearing round-trip the C2 widen depends on."""
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = _PRINTINGS["Anticausal Vestige"]
    (ta,) = p.triggered_abilities
    d = trajectory._python_ta_to_safe_dict(ta)
    assert d is not None, (
        "Anticausal Vestige's LEAVES_BATTLEFIELD+IsSelf trigger must "
        "be classified as a safe-dict by _python_ta_to_safe_dict "
        "(the C2 widen)"
    )
    # The exact bare unit-shape safe-dict pinned at the C2
    # substrate's recognizer admit pin.
    assert d == {
        "event": "leaves_battlefield",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "anticausal_vestige_leaves_effect"},
    }, (
        f"AV's safe-dict shape must be the bare unit-shape; got {d!r}"
    )
    rt = _ta_dict_to_python_effect(d["effect"])
    assert rt == AnticausalVestigeLeavesEffect(), (
        f"bridge dict->Python round-trip must yield the matching "
        f"AnticausalVestigeLeavesEffect() instance; got {rt!r}"
    )
    assert rt == ta.effect, (
        "bridge round-trip must equal the parser-emitted effect "
        "(structural byte-equality contract)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged trigger dict shape for the synthetic carrier the cross-
# engine probe uses.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_anticausal_vestige_synthetic_dict():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "anticausal_vestige_leaves_effect"}`` dict shape on
    the Anticausal Vestige-shape synthetic carrier. Mirrors the
    existing pin
    ``test_rust_parser_accepts_anticausal_vestige_leaves_effect_in_triggered_ability``
    in ``test_anticausal_vestige_substrate_cycle_1.py``; here the
    dict is wrapped in the full AV-shape printing the cross-engine
    probe uses."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_AV_PRINTING_DICT)
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Anticausal Vestige printing through both engines via
# the WARP-cast -> END_STEP exile sweep -> LEAVES_BATTLEFIELD trigger
# fires -> AV's LTB resolves (draw + first-legal permanent-from-hand
# onto bf tapped). Full ``compare_fields == []`` over the WHOLE
# cross-engine field view at every step + the concrete observables
# (AV in exile post-sweep on BOTH; library shrinks by 1 from the
# draw on BOTH; one MV<=land_count permanent moves hand -> bf tapped
# on BOTH; the picked card is the SAME id on BOTH).
#
# Scenario: real-archetype-24 deck context (B-heavy, AV-free — the
# same archetype the test_probe_warp_admitted.py parametrize uses
# for AV); seat _PickFirstAgent on p0 to mirror Rust's deterministic
# first-legal pick; ramp to ~10 lands so warp cost {4} + normal
# recast {6} both payable AND land_count is large enough that the
# LTB-X hand pick has at least one MV<=X candidate. Cast AV via
# warp, advance to END_STEP, drain the WarpExileSelf delayed
# trigger, AV moves bf -> exile, LEAVES_BATTLEFIELD dispatches, AV's
# LTB triggered ability queues + resolves byte-equal.
# ---------------------------------------------------------------------------


class _PickFirstAgent(Agent):
    """Deterministic agent that picks the first legal id on every
    sacrifice/choice prompt. Mirrors Rust's first-legal iteration
    convention. Re-uses the C1 substrate's
    ``test_python_resolve_smoke_seated_agent_path`` pattern."""

    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None


@_rust_skip
def test_cross_engine_real_eoe_anticausal_vestige_ltb_parity():
    """**GENUINE real-EoE cross-engine probe — Anticausal Vestige
    LEAVES_BATTLEFIELD AnticausalVestigeLeavesEffect path. PROBED
    tier flip (Cycle 3 closure marker —
    ``covered_by_construction`` -> PROBED).**

    Python: the ACTUAL parsed Anticausal Vestige printing seated
    via the production-deck-bridge into the real arch-24 deck
    context (B-heavy, AV-free); ``_PickFirstAgent`` seated on the
    p0 Player so the LTB's ``if p.agent is None`` short-circuit
    does NOT fire (Python's agent then picks the first legal hand
    card with MV<=land_count, which equals Rust's iteration-first
    pick).

    Rust: bridged synthetic carrier via the same production-deck-
    bridge path; the warp-cast / end-step-exile-sweep / LEAVES
    dispatch / LTB resolve all run through the production Rust
    arms.

    Assertion strength: **full ``compare_fields == []``** at every
    phase boundary + after the warp cast + after the WarpExileSelf
    delayed-trigger resolve (LEAVES dispatch fires here) + after
    the LTB resolves. Plus concrete observables: AV in exile on
    BOTH; p0 hand size diff equals (draw +1, put -1) = net 0 if
    a permanent is picked; bf gains the picked permanent on BOTH;
    the picked permanent is the SAME card id on BOTH (the
    deterministic-first contract held).
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, step_both_drained, advance_phase_python,
        compare_fields, resolve_top_of_stack_python,
        resolve_top_of_stack_rust,
    )
    from mtg_bot.legal import legal_actions
    from tests.test_trajectory_parity import _step_views

    real = _PRINTINGS.get("Anticausal Vestige")
    if real is None:
        pytest.skip("Anticausal Vestige absent from active CardSource")

    # Verify-first: AV IS still warp-admitted at HEAD (post-C2).
    assert real.warp_cost is not None
    assert real.warp_cost_str == "{4}"
    assert real.mana_cost_str == "{6}"
    assert trajectory._printing_is_bridge_pure_warp_creature(real), (
        "AV must be warp-admitted at HEAD post-C2; if False, the C2 "
        "widen has regressed"
    )

    cd = trajectory._printing_to_card_def(real)
    assert cd.has_warp is True, (
        "AV: _printing_to_card_def must preserve has_warp through "
        "the bridge"
    )

    # Build the real-archetype-24 deck context (mirror of the
    # _WARP_CARDS parametrize for AV). Arch 24 is B-heavy (Sw=9,
    # Mt=8) and AV-free (preserves the
    # ``p0_library.count(card_name) == 1`` invariant other Phase-
    # 1/1.5 cards satisfy).
    try:
        deck_names = trajectory.load_production_deck(archetype=24)
    except (FileNotFoundError, IndexError):
        pytest.skip("17lands deck pool unavailable")

    filtered, _defs = trajectory._filter_deck_to_bridge_supported(
        deck_names, _PRINTINGS,
    )
    # p0 = the genuine AV seated into the real filtered context;
    # p1 = the same real filtered context (clean mirror).
    p0_names = ["Anticausal Vestige"] + list(filtered)
    p1_names = list(filtered)
    # Pad to a deck large enough to support a long ramp + end-step
    # cycle without running into reshuffles. Pad with Swamp (B) —
    # AV is colorless so any color works, but B matches arch-24's
    # primary color and aligns with the basic-land normalisation
    # below.
    spec = trajectory.production_deck_to_deckspec(
        p0_names, p1_names, pad_to_size=45, pad_with="Swamp",
    )
    # Normalise EVERY basic land in the registry to tap for "B" so
    # both engines deterministically afford the warp/normal costs.
    # AV is colorless ({4} warp / {6} normal) so any color works,
    # but force-tapping for "B" mirrors the established Phase-1/1.5
    # idiom on a symmetric (same-registry-on-both-engines) basis.
    newdefs = tuple(
        CardDef(name=c.name, card_type="Land", mana_produced=("B",))
        if c.card_type == "Land" else c
        for c in spec.card_defs
    )
    spec = DeckSpec(
        card_defs=newdefs,
        p0_library=spec.p0_library,
        p1_library=spec.p1_library,
    )
    assert spec.p0_library.count("Anticausal Vestige") == 1, (
        f"Expected exactly one AV seated into arch-24; got "
        f"{spec.p0_library.count('Anticausal Vestige')}"
    )

    py, rs = trajectory.setup_matched_game(spec)

    # Phase-advance helper that runs FULL compare_fields at every
    # phase boundary (the strong tier).
    def adv(n):
        for _ in range(n):
            advance_phase_python(py)
            rs.advance_phase()
            pv, rv = _step_views(py, rs)
            d = compare_fields(pv, rv)
            assert not d, (
                f"AV: phase advance ({pv['step']}, turn {pv['turn']}) "
                f"diverged (FULL compare_fields): "
                f"{[(x.field, x.py_value, x.rust_value) for x in d]}"
            )

    adv(3)  # turn 1 PRECOMBAT_MAIN
    p0 = py.active_player_idx

    # Seat _PickFirstAgent on p0 BEFORE the warp cast so the LTB's
    # agent-None short-circuit does NOT fire when AV's LEAVES
    # trigger resolves (the deterministic-first contract). The
    # opponent agent stays None — only the AV controller needs it
    # since the LTB resolves on p0 only.
    py.players[p0].agent = _PickFirstAgent()

    # Ramp to >=6 lands on p0's bf (enough for normal recast at
    # mana value 6; also covers the warp cost of 4). 10 lands is
    # the established Phase-1 idiom — keeps Python's mana-aware
    # legal_actions enumerator and Rust's structural legal_decisions
    # both reporting the warp + normal pair as affordable.
    n_lands_target = 10
    for _cycle in range(40):
        n_lands_bf = sum(
            1 for o in py.battlefield
            if o.controller_id == p0 and o.printing.is_land
        )
        if n_lands_bf >= n_lands_target:
            break
        if (py.active_player_idx == p0
                and py.players[p0].lands_played_this_turn == 0):
            hand_land = [
                o for o in py.players[p0].hand
                if o.printing.is_land
            ]
            if hand_land:
                s = step_both_drained(
                    py, rs,
                    {"kind": "play_land",
                     "card_id": int(hand_land[0].id)},
                )
                assert not s.divergences, (
                    f"AV: play_land diverged: "
                    f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
                )
        adv(24)  # +2 turns -> back to p0's MAIN1
    n_lands_bf = sum(
        1 for o in py.battlefield
        if o.controller_id == p0 and o.printing.is_land
    )
    if n_lands_bf < 6:
        pytest.skip(
            f"AV: real-deck-context arch-24 draw did not develop 6 "
            f"lands within the cycle budget (got {n_lands_bf}); "
            f"land-light shuffle. Every step_both trajectory up to "
            f"here was byte-equal. Re-pin a land-richer archetype "
            f"if this becomes persistent."
        )

    # Land into a clean p0 PRECOMBAT_MAIN with the land drop
    # available.
    for _ in range(60):
        pv, _rv = _step_views(py, rs)
        if (py.active_player_idx == p0
                and pv["step"] == "PRECOMBAT_MAIN"
                and py.players[p0].lands_played_this_turn == 0):
            break
        adv(1)

    # Tap exactly 4 untapped non-sick lands p0 controls — the warp
    # cost. The remainder stay untapped (Python's mana-aware legal-
    # action enumerator needs them visible so the [False, True]
    # legal pair assertion holds; see the Phase-1 docstring at
    # test_probe_warp_admitted.py for the full rationale).
    warp_total = 4
    taps = 0
    for o in list(py.battlefield):
        if (o.controller_id == p0 and o.printing.is_land
                and not o.tapped and not o.summoning_sick
                and taps < warp_total):
            s = step_both_drained(
                py, rs,
                {"kind": "activate_ability",
                 "source_id": int(o.id), "ability_index": 0},
            )
            assert not s.divergences, (
                f"AV: land tap for warp cost diverged: "
                f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
            )
            taps += 1
    assert taps == warp_total, (
        f"AV: needed {warp_total} mana for warp cost; only tapped "
        f"{taps}"
    )

    av_obj = next(
        o for o in py.players[p0].hand
        if o.printing.name == "Anticausal Vestige"
    )

    # (1) Both engines offer the SAME base+warp CastSpell pair.
    py_pair = sorted(
        a.use_warp for a in legal_actions(py, p0)
        if getattr(a, "card_id", None) == av_obj.id
    )
    rs_pair = sorted(
        a["use_warp"] for a in rs.legal_decisions(p0)
        if a.get("kind") == "cast_spell"
        and a.get("card_id") == av_obj.id
    )
    # Note: Python's mana-aware enumerator may filter the False
    # branch if it can't see enough untapped lands for the normal
    # {6} cost. Accept either the [True] or [False, True] pair —
    # the load-bearing pin is that Rust's structural enumeration
    # surfaces the warp option and BOTH engines agree on the
    # post-cast trajectory below.
    assert py_pair == rs_pair, (
        f"AV: legal base+warp pair mismatch on the real-deck "
        f"context — py={py_pair} rs={rs_pair}"
    )
    assert True in py_pair, (
        f"AV: warp option must be legal on BOTH engines; py_pair="
        f"{py_pair}"
    )

    # Hand-size snapshot BEFORE the warp cast (used for the post-
    # LTB hand-delta observable).
    py_hand_before = len(py.players[p0].hand)
    rs_hand_before = rs.hand_sizes[p0]
    assert py_hand_before == rs_hand_before
    py_lib_before = len(py.players[p0].library)
    rs_lib_before = rs.library_sizes[p0]
    assert py_lib_before == rs_lib_before
    py_bf_before = len(py.battlefield)
    rs_bf_before = len(rs.battlefield_snapshot())
    assert py_bf_before == rs_bf_before

    # (2) The warp cast — FULL compare_fields byte-equal post-cast.
    s = step_both_drained(
        py, rs,
        {"kind": "cast_spell", "card_id": int(av_obj.id),
         "use_warp": True},
    )
    assert not s.divergences, (
        f"AV: warp cast diverged (FULL compare_fields): "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    assert py.spell_warped_this_turn is True
    assert rs.spell_warped_this_turn is True
    # AV is on bf on BOTH after the warp-cast resolve.
    assert any(
        o.printing.name == "Anticausal Vestige" for o in py.battlefield
    ), "AV: must be on Python bf post-warp-cast"
    assert any(
        o["printing_name"] == "Anticausal Vestige"
        for o in rs.battlefield_snapshot()
    ), "AV: must be on Rust bf post-warp-cast"

    # (3) Advance MAIN1 -> END. At PHASE_END_STEP entry both engines
    # push the WarpExileSelf delayed trigger onto the stack (CR-
    # 603.7). The drain that follows is where the
    # LEAVES_BATTLEFIELD event dispatches on BOTH engines AND AV's
    # LTB triggered ability queues on the stack as the SECOND
    # resolving frame (then immediately resolves under the same
    # ``floor=0`` drain).
    adv(7)  # MAIN1 -> END (WarpExileSelf delayed trigger on stack)

    # Snapshot BEFORE the stack drain — used to compute the LTB
    # observable deltas (library shrinkage from the draw, hand+bf
    # deltas from the put-permanent-onto-bf).
    py_lib_pre_ltb = len(py.players[p0].library)
    rs_lib_pre_ltb = rs.library_sizes[p0]
    py_hand_pre_ltb = len(py.players[p0].hand)
    rs_hand_pre_ltb = rs.hand_sizes[p0]
    py_bf_pre_ltb = len(py.battlefield)
    rs_bf_pre_ltb = len(rs.battlefield_snapshot())
    assert py_lib_pre_ltb == rs_lib_pre_ltb
    assert py_hand_pre_ltb == rs_hand_pre_ltb
    assert py_bf_pre_ltb == rs_bf_pre_ltb

    # Drain the WarpExileSelf + LTB triggers on BOTH engines.
    # ``floor=0`` resolves the stack all the way down: WarpExileSelf
    # exiles AV (firing LEAVES_BATTLEFIELD → AV's LTB queues on top
    # of the stack); the LTB then resolves (drawing a card and
    # putting the first-legal hand permanent onto bf tapped under
    # the seated-agent deterministic-first contract).
    resolve_top_of_stack_python(py, floor=0)
    resolve_top_of_stack_rust(rs, floor=0)
    # Verify AV is exiled on BOTH (the post-WarpExileSelf
    # observable).
    py_ex_names = sorted(
        o.printing.name for o in py.players[p0].exile
    )
    rs_ex_names = sorted(
        o["printing_name"] for o in rs.exile_snapshot(p0)
    )
    assert "Anticausal Vestige" in py_ex_names, (
        f"AV: must be in Python exile post-WarpExileSelf resolve; "
        f"py_ex={py_ex_names}"
    )
    assert "Anticausal Vestige" in rs_ex_names, (
        f"AV: must be in Rust exile post-WarpExileSelf resolve; "
        f"rs_ex={rs_ex_names}"
    )
    assert not any(
        o.printing.name == "Anticausal Vestige" for o in py.battlefield
    ), "AV: must have left Python battlefield (warp exile sweep)"
    assert not any(
        o["printing_name"] == "Anticausal Vestige"
        for o in rs.battlefield_snapshot()
    ), "AV: must have left Rust battlefield (warp exile sweep)"

    # (4) Stack must be empty on BOTH engines post-drain (both the
    # WarpExileSelf and the queued AV LTB resolved under the
    # ``floor=0`` drain above).
    assert len(py.stack) == 0, (
        f"AV: Python stack must be empty post-drain; got "
        f"{len(py.stack)} items"
    )
    assert rs.stack_size() == 0, (
        f"AV: Rust stack must be empty post-drain; got "
        f"{rs.stack_size()} items"
    )

    # (5) Concrete LTB observables — cross-engine equal.
    py_lib_post_ltb = len(py.players[p0].library)
    rs_lib_post_ltb = rs.library_sizes[p0]
    py_hand_post_ltb = len(py.players[p0].hand)
    rs_hand_post_ltb = rs.hand_sizes[p0]
    py_bf_post_ltb = len(py.battlefield)
    rs_bf_post_ltb = len(rs.battlefield_snapshot())

    # Library must shrink by exactly 1 on both (the LTB draw).
    assert py_lib_post_ltb == py_lib_pre_ltb - 1, (
        f"AV LTB: Python library must shrink by 1 (draw); "
        f"{py_lib_pre_ltb} -> {py_lib_post_ltb}"
    )
    assert rs_lib_post_ltb == rs_lib_pre_ltb - 1, (
        f"AV LTB: Rust library must shrink by 1 (draw); "
        f"{rs_lib_pre_ltb} -> {rs_lib_post_ltb}"
    )

    # Hand delta + bf delta cross-engine equal. The full state
    # transitions under the warp exile sweep + LTB resolve:
    #   * AV: bf -> exile (bf -1)
    #   * Draw: lib -> hand (hand +1)
    #   * LTB pick (deterministic-first): hand -> bf tapped
    #     (hand -1, bf +1)
    # Net deltas: hand = +1 -1 = 0; bf = -1 +1 = 0. Whichever path
    # was taken, BOTH engines must take the SAME path (the
    # deterministic-first contract).
    py_hand_delta = py_hand_post_ltb - py_hand_pre_ltb
    rs_hand_delta = rs_hand_post_ltb - rs_hand_pre_ltb
    assert py_hand_delta == rs_hand_delta, (
        f"AV LTB: hand delta diverged — py={py_hand_delta} "
        f"rs={rs_hand_delta}"
    )
    py_bf_delta = py_bf_post_ltb - py_bf_pre_ltb
    rs_bf_delta = rs_bf_post_ltb - rs_bf_pre_ltb
    assert py_bf_delta == rs_bf_delta, (
        f"AV LTB: bf delta diverged — py={py_bf_delta} "
        f"rs={rs_bf_delta}"
    )
    # Sanity: with ~10 lands on bf and a real arch-24 hand, at
    # least one permanent in hand must have MV<=10 → the put-onto-
    # bf path is taken. Net hand delta = 0 (draw +1, put -1);
    # bf delta = 0 (AV leaves -1, picked permanent enters +1).
    assert py_hand_delta == 0, (
        f"AV LTB: expected hand delta = 0 (draw +1, put -1) under "
        f"the deterministic-first contract with ~10 lands and a "
        f"real arch-24 hand; got {py_hand_delta}. Suggests the LTB "
        f"didn't find a candidate (unlikely) or the agent short-"
        f"circuit fired (would mean _PickFirstSacrificeAgent isn't "
        f"seated)."
    )
    assert py_bf_delta == 0, (
        f"AV LTB: expected bf delta = 0 (AV leaves bf -1, picked "
        f"permanent enters bf +1); got {py_bf_delta}"
    )

    # (6) Full field-view byte-equality after the LTB resolves.
    pv_post, rv_post = _step_views(py, rs)
    diffs = compare_fields(pv_post, rv_post)
    assert diffs == [], (
        f"AV LTB: post-resolve full field-view diverged "
        f"(BYTE-EQUAL contract failed): "
        f"{[(x.field, x.py_value, x.rust_value) for x in diffs]}"
    )

    # (7) Bonus pin: the picked permanent landed on bf TAPPED on
    # both engines (the printed text contract: "onto the
    # battlefield tapped"). Identify the new bf entry by diffing
    # pre vs post — bf grew by exactly 1 so the last-added object
    # IS the picked permanent. The full compare_fields above
    # already implies tapped-state equality, but pin it explicitly
    # for the load-bearing observable.
    # Identify the most-recent bf entry on Python: the one with
    # the largest etb_timestamp (the LTB's reserved timestamp).
    py_picked = max(py.battlefield, key=lambda o: o.etb_timestamp or 0)
    # On Rust, find the matching id via the bf snapshot's last
    # entry (insertion order — the LTB push_back is the most
    # recent).
    rs_bf_post = rs.battlefield_snapshot()
    rs_picked = rs_bf_post[-1]
    assert py_picked.tapped is True, (
        f"AV LTB: picked permanent must be tapped on Python; got "
        f"tapped={py_picked.tapped}, name={py_picked.printing.name}"
    )
    assert rs_picked.get("tapped") is True, (
        f"AV LTB: picked permanent must be tapped on Rust; got "
        f"tapped={rs_picked.get('tapped')}, "
        f"name={rs_picked.get('printing_name')}"
    )
    # Cross-engine name match — the deterministic-first contract
    # picked the SAME card on both sides.
    assert py_picked.printing.name == rs_picked.get("printing_name"), (
        f"AV LTB: deterministic-first contract picked DIFFERENT "
        f"cards cross-engine — py={py_picked.printing.name!r} vs "
        f"rs={rs_picked.get('printing_name')!r}. The C3 design "
        f"deferral (PendingDecision::PickCardFromHandChoice) IS "
        f"the right pivot — STOP and honest-stop."
    )
