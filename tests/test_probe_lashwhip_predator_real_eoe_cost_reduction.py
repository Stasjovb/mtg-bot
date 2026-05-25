"""Lashwhip Predator Cycle 4 — per-card real-EoE cross-engine byte-
equality probe (``covered_by_construction`` → PROBED tier flip; the
FINAL probe of cost-reduction Phase 1).

Lashwhip Predator is a ``{4}{G}{G}`` Creature — Plant Beast (5/7 with
reach, EoE — sourced from ``data/edge_of_eternities.json``) with a
single Phase-1 boolean-condition cost-reduction rider:

    "This spell costs {2} less to cast if an opponent controls three
    or more creatures."

Parsed into one
``CostReduction(amount=2, condition=OpponentsControlAtLeast(filter=
IsCreature(), n=3))`` under ``printing.cost_reductions``. No spell
effect, no triggered or activated abilities, no warp/impending/static/
external riders — the cleanest Sub-shape-A Phase-1 carrier modulo the
``reach`` static keyword (admitted via the C2 predicate's
``_SAFE_KEYWORDS`` allowance, sibling to the round-63 warp-Phase-1
shape — per ``docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md`` §2 /
§3 admit table).

**Multi-cycle DECLINED → ADMITTED → PROBED transition (this lane is
the closure marker for Phase 1).**

  * **Cycle 1 (substrate, commit ``3683e62e``).** Rust
    ``CostReduction`` + ``Condition`` enum + ``Printing.cost_
    reductions`` field + parse path + Cycle-1 evaluator hook +
    ``set_spells_cast_this_turn`` getter/setter shipped; Lashwhip
    stayed DECLINED at the admit gate (the substrate had no admit
    predicate yet — the §2 "no auto-grow before the bridge" pin
    pinned the Cycle 1 lockstep).
  * **Cycle 2 (THE FLIP, commit ``8593b0fb``, 2026-05-24).** Rust
    ``apply_cost_reductions_rust`` (``state_ops_legal.rs:742`` —
    the seam-extending real evaluator) walks both Phase-1
    Condition variants. For Lashwhip's ``OpponentsControlAtLeast
    { type_filter: Creature, count: n }`` arm the helper scans
    every opponent's battlefield, sums permanents whose
    ``card_types`` contains ``"Creature"``, and tests the sum
    against ``n`` — early-out on first satisfied count
    (``state_ops_legal.rs:788-825``). The bridge round-trip on
    the Python ``cost_reductions`` axis (``_printing_to_card_def``
    + ``_spec_card_to_printing_dict`` + ``_card_def_to_python_
    printing``) emits the canonical
    ``(2, "opponents_control_at_least", ("creature", 3))`` triple;
    the new admit predicate
    ``_printing_is_bridge_pure_cost_reduction_creature`` flipped
    Lashwhip simultaneously with Gigastorm DECLINED → ADMITTED
    (the 2-card 24,908-deck single-cycle FLIP; pin #3 — admit set
    EXACTLY ``{"Gigastorm Titan", "Lashwhip Predator"}``).
  * **Cycle 3 (commit ``1f13f092``, 2026-05-25).** Gigastorm
    Titan's per-card real-EoE byte-equal probe landed —
    ``covered_by_construction`` → PROBED on the
    ``AnotherSpellCastThisTurn`` carrier.
  * **Cycle 4 (THIS LANE; the FINAL probe of Phase 1).** Per-card
    real-EoE cross-engine byte-equality probe driving BOTH
    lifecycles (full-cost cast with opponents controlling <3
    creatures + reduced-cost cast with ≥3 opponent creatures
    pre-seated) flips ``covered_by_construction`` → PROBED in the
    pool-parity metric. Lashwhip is the SECOND and LAST Phase-1
    cost-reduction carrier; with this commit, BLOCKED drops
    59 → 58 and Phase 1 closure is complete (~24,908 17lands
    decks unblocked at the admit gate over Cycles 2 + 3 + 4).

**Lifecycle coverage.** Both Phase-1 cost-reduction paths are
exercised through ``OpponentsControlAtLeast(IsCreature(), 3)``:

  * **Full-cost lifecycle (lifecycle A).** Pre-cast state: NO
    opponent creatures on the battlefield. Lashwhip pays its base
    ``{4}{G}{G}`` — the ``OpponentsControlAtLeast`` condition is
    False (0 opponent creatures < 3), the reduction does NOT
    apply. Pool primed with 4 colorless + 2 green on both engines
    so ``auto_tap_pay_for_cost`` (Rust) / ``auto_tap_for_cost``
    (Python) drain the pool cleanly without needing lands.
    Asserts full ``compare_fields == []`` post-cast: pool empty
    on both, Lashwhip on the stack on both.
  * **Reduced-cost lifecycle (lifecycle B).** Pre-cast state: 3
    vanilla creatures pre-seated on opponent's (p1's) battlefield
    via the scripted picker — ``register_and_inject_object`` on
    Rust (controller=1, zone=ZONE_BATTLEFIELD) + ``new_object`` +
    ``state.battlefield.append`` on Python (owner_id=1,
    zone=Zone.BATTLEFIELD). Lashwhip's
    ``OpponentsControlAtLeast(IsCreature(), 3)`` is True; the
    reduction applies and the helper returns ``{2}{G}{G}``. Pool
    primed with 2 colorless + 2 green on both engines. Asserts
    full ``compare_fields == []`` post-cast: pool empty on both,
    NO residual generic (the ``{2}`` reduction was actually
    applied, NOT silently paid through 4 colorless), Lashwhip on
    the stack on both, 3 opponent creatures still on opp's bf.

**This is the LOAD-BEARING evidence for the Cycle-2 FLIP's second
carrier.** The C2 admit predicate trusted
``apply_cost_reductions_rust`` to mirror Python's
``apply_cost_reductions`` byte-equal for the Phase-1
``OpponentsControlAtLeast`` shape; this probe is the per-card proof
that the round-46 real-EoE-signal discipline ('do NOT trust
synthetic CardDefs; drive the live ``OracleParserCardSource``
printing') holds at the cast-and-pay level for the
battlefield-scanning condition variant, not just at the
substrate fixture level. The cycle-3 sibling probe pinned the
``AnotherSpellCastThisTurn`` carrier; this probe pins the
``OpponentsControlAtLeast`` carrier — together they exhaust the
Phase-1 Condition variant surface byte-equal.

The post-resolve permanent-on-bf check sits outside this probe's
scope (parallel to the Cycle-3 sibling) — the cast-and-pay path
is the part the Cycle 2 substrate touched; the resolve path was
unchanged. This module concentrates on the cost-payment
byte-equality: pool debit, generic/colored split, and the
opponent-battlefield scan that powers the Lashwhip reduction.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built — mirrors the
# project-wide policy for cross-engine probes.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the established pattern in
    sibling per-card parity probes."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# (1) Parser SoT — Lashwhip Predator is parser-claimed and emits the
# expected Phase-1 cost-reduction shape (the Cycle-1 substrate pin,
# duplicated here so this module is self-contained for the PROBED-tier
# evidence).
# ---------------------------------------------------------------------------


def test_lashwhip_predator_parser_claims_card():
    assert "Lashwhip Predator" in _PRINTINGS, (
        "Lashwhip Predator must be parser-claimed by the active "
        "CardSource (EoE set)"
    )


def test_lashwhip_predator_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, the
    ``reach`` static keyword, single Phase-1 cost-reduction rider;
    no other riders)."""
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.effects.conditions import OpponentsControlAtLeast
    from mtg_bot.effects.object_predicates import IsCreature

    p = _PRINTINGS["Lashwhip Predator"]
    assert p.mana_cost_str == "{4}{G}{G}"
    assert "Creature" in p.card_types
    assert "Plant" in p.subtypes
    assert "Beast" in p.subtypes
    assert p.power == 5
    assert p.toughness == 7
    assert "reach" in p.keywords
    # Phase-1 boolean cost-reduction rider — the load-bearing shape.
    assert len(p.cost_reductions) == 1
    (rule,) = p.cost_reductions
    assert isinstance(rule, CostReduction)
    assert rule.amount == 2
    assert isinstance(rule.condition, OpponentsControlAtLeast)
    assert isinstance(rule.condition.filter, IsCreature)
    assert rule.condition.n == 3
    # No external_cost_reductions / spell_effect / abilities / warp /
    # impending — the cleanest Sub-shape-A carrier (modulo reach,
    # which is in ``_SAFE_KEYWORDS``) per the design doc §2.
    assert p.external_cost_reductions == ()
    assert not p.triggered_abilities
    assert not p.activated_abilities
    assert not p.static_abilities
    assert p.spell_effect is None
    assert p.warp_cost is None


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — Python printing → CardDef → Rust dict →
# Python printing round-trips byte-equal on the cost_reductions axis.
# Duplicated from the Cycle-2 substrate pin so the per-card module is
# self-contained for the PROBED-tier evidence.
# ---------------------------------------------------------------------------


def test_lashwhip_predator_bridge_round_trip_byte_equal():
    """The Cycle-2 bridge: Python printing → ``_printing_to_card_def``
    → ``CardDef.cost_reductions`` triple → ``_spec_card_to_printing_
    dict`` Rust dict → ``Registry.register_printing`` → ``_card_def_
    to_python_printing`` Python printing whose ``cost_reductions`` is
    byte-equal to the live-parsed input."""
    import mtg_bot_engine
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.effects.conditions import OpponentsControlAtLeast
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    p_orig = _PRINTINGS["Lashwhip Predator"]
    cd = trajectory._printing_to_card_def(p_orig)
    assert cd.cost_reductions == (
        (2, "opponents_control_at_least", ("creature", 3)),
    )
    d = _spec_card_to_printing_dict(cd)
    assert d.get("cost_reductions") == [
        {
            "amount": 2,
            "condition_kind": "opponents_control_at_least",
            "condition_args": ("creature", 3),
        },
    ]
    # Rust registry accepts the dict — no panic, no Err.
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(d)
    assert isinstance(pid, int)
    # Python reverse arm rematerializes a byte-equal CardPrinting.
    p_rt = _card_def_to_python_printing(cd)
    assert p_rt.cost_reductions == p_orig.cost_reductions
    (rule_rt,) = p_rt.cost_reductions
    assert isinstance(rule_rt, CostReduction)
    assert rule_rt.amount == 2
    assert isinstance(rule_rt.condition, OpponentsControlAtLeast)
    assert isinstance(rule_rt.condition.filter, IsCreature)
    assert rule_rt.condition.n == 3


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the Phase-1 cost-reduction
# condition tag ``opponents_control_at_least`` parses on a
# Lashwhip-shape printing via ``register_and_inject_object``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_lashwhip_predator_synthetic_dict():
    """Lockstep pin: Rust's parse arm accepts the
    ``{"amount": 2, "condition_kind": "opponents_control_at_
    least", "condition_args": ("creature", 3)}`` payload on a
    Lashwhip-shape synthetic carrier (the dict shape
    ``_spec_card_to_printing_dict`` emits)."""
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sid = rs.register_and_inject_object(
        {
            "name": "Lashwhip Predator (synthetic carrier)",
            "card_types": ["Creature"],
            "subtypes": ["Plant", "Beast"],
            "mana_cost": {"generic": 4, "G": 2},
            "power": 5,
            "toughness": 7,
            "cost_reductions": [
                {
                    "amount": 2,
                    "condition_kind": "opponents_control_at_least",
                    "condition_args": ("creature", 3),
                },
            ],
        },
        0, 0,  # zone 0 = hand
    )
    assert isinstance(sid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — full-cost
# lifecycle. PROBED tier flip (one of two lifecycles in this Cycle-4
# closure marker — ``covered_by_construction`` → PROBED, lifecycle A).
#
# Lifecycle A: cast Lashwhip with NO opponent creatures on the
# battlefield. The OpponentsControlAtLeast(IsCreature(), 3) condition
# is False (0 < 3) and the reduction does NOT apply. Both engines
# must pay the base {4}{G}{G}.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_lashwhip_predator_full_cost_no_opp_creatures_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Lashwhip Predator
    full-cost lifecycle (cast with NO opponent creatures on the
    battlefield). PROBED tier flip evidence (Cycle 4 closure
    marker — ``covered_by_construction`` → PROBED, lifecycle A).**

    Pre-cast state on both engines: opponent (p1) controls 0
    creatures, Lashwhip in p0's hand, p0's mana pool primed with
    {4}{G}{G} (4 colorless + 2 green, exactly the base
    ``mana_cost`` Lashwhip needs when its reduction does not apply).
    No spells previously cast, no other permanents on either
    battlefield.

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, lashwhip_id)``
        drives the full Python cast pipeline (selects empty
        targets, applies cost reductions [no-op — the condition
        ``OpponentsControlAtLeast(IsCreature(), 3).matches`` is
        False on a state with 0 opp creatures, per
        ``effects/conditions.py:219-228``], pays via
        ``auto_tap_for_cost``, pushes the ``StackItem``,
        increments ``spells_cast_this_turn``, fires IS_CAST).
      * **Rust.** ``cast_creature(lashwhip_id, 0)`` drives the
        full Rust cast pipeline. The
        ``apply_cost_reductions_rust(state, idx, printing, base)``
        helper scans every opponent's battlefield for permanents
        whose ``card_types`` contains ``"Creature"`` — 0 here —
        so the False condition short-circuits and the base
        ``{4}{G}{G}`` cost is returned untouched. Pays via
        ``auto_tap_pay_for_cost``, rehomes to the stack-source
        store, dispatches Event::Cast, pushes the StackItem.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack. Mana pool MUST
    be empty on both (the full {4}{G}{G} was paid — no silent
    over-spend), Lashwhip MUST be off the hand and on the
    stack on both, both battlefields MUST stay empty.

    The probe deliberately uses pool-primed mana (not lands) so
    the cost-payment is a pure pool drain — the cost-reduction
    arithmetic is the entire load-bearing signal on this lifecycle
    (no land-tapping noise; ``auto_tap_pay_for_cost`` drains the
    pool exactly as ``auto_tap_for_cost`` does on Python).
    """
    from mtg_bot.actions import _cast_spell
    from mtg_bot.game import ManaCoin, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    real = _PRINTINGS.get("Lashwhip Predator")
    if real is None:
        pytest.skip("Lashwhip Predator absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat Lashwhip in p0's hand; prime p0's pool with
    # 4 colorless + 2 green. NO opponent creatures.
    py_l = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_l)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="G"),
        ManaCoin(color="G"),
    ])
    # Sanity: opp (p1) battlefield is empty — the
    # OpponentsControlAtLeast(IsCreature(), 3) condition is False
    # (0 opp creatures < 3); the {2} reduction must NOT apply,
    # both engines pay {4}{G}{G}.
    assert not py.battlefield

    # ---- Rust: register a Lashwhip-shape carrier in p0's hand;
    # prime p0's pool identically. The bridge round-trip (test 2)
    # already pinned the Python printing → Rust dict shape; reuse
    # the same canonical dict here for the carrier injection.
    rs_l = rs.register_and_inject_object(
        {
            "name": "Lashwhip Predator",
            "card_types": ["Creature"],
            "subtypes": ["Plant", "Beast"],
            "mana_cost": {"generic": 4, "G": 2},
            "power": 5,
            "toughness": 7,
            "cost_reductions": [
                {
                    "amount": 2,
                    "condition_kind": "opponents_control_at_least",
                    "condition_args": ("creature", 3),
                },
            ],
        },
        0, 0,  # zone 0 = HAND
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "G", 1)
    rs.add_mana(0, "G", 1)

    # Pre-cast sanity: nothing on the stack on either engine.
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_l.id)
    ok = rs.cast_creature(rs_l, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Lashwhip Predator at "
        "full {4}{G}{G} cost with a {4}{G}{G}-primed pool"
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty (the {4}{G}{G} was paid exactly — no
    # residual mana, no silent over-spend).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (cost {{4}}{{G}}{{G}} "
        f"paid exactly); got {py.players[0].mana_pool}"
    )
    # Hand emptied (Lashwhip moved onto the stack source).
    assert all(o.id != py_l.id for o in py.players[0].hand), (
        "Python: Lashwhip must leave hand post-cast"
    )
    # Stack carries Lashwhip.
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_l.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast; got {rs_pool}"
    )
    # Stack carries Lashwhip. The successful cast with exactly the
    # {4}{G}{G}-primed pool proves the reduction did NOT apply
    # (auto_tap_pay_for_cost would have short-spent if Rust returned
    # a reduced cost on a 0-opp-creatures state — and the pool would
    # carry residual mana).
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Lashwhip Predator full-cost lifecycle (cast with 0 opp "
        f"creatures on bf) must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — reduced-cost
# lifecycle. PROBED tier flip (one of two lifecycles in this Cycle-4
# closure marker — ``covered_by_construction`` → PROBED, lifecycle B).
# This is THE load-bearing case the C2 bridge admit predicate trusts:
# both engines apply the {2} reduction byte-equal after a battlefield
# scan finds ≥3 opponent creatures.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_lashwhip_predator_reduced_cost_three_opp_creatures_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Lashwhip Predator
    reduced-cost lifecycle (cast with 3 opponent creatures
    pre-seated on opp's battlefield). PROBED tier flip evidence
    (Cycle 4 closure marker — ``covered_by_construction`` →
    PROBED, lifecycle B). THIS is the load-bearing probe: the
    {2} reduction must apply byte-equal on both engines after
    scanning the opponent's battlefield.**

    Pre-cast state on both engines: 3 vanilla 2/2 Bear-shape
    creatures pre-seated on p1's battlefield (the "scripted
    picker" per the design doc §7.3 — forcing the ≥3-opp-
    creatures state without having to walk a full turn through
    casts of 3 cheap opponent creatures). Lashwhip in p0's hand.
    p0's mana pool primed with {2}{G}{G} on both engines — the
    EXACT reduced cost: the {2} reduction subtracts 2 generic
    from the {4}{G}{G} base, so the pay-time cost is {2}{G}{G}.

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, lashwhip_id)``
        drives the full Python cast pipeline: selects empty
        targets, applies cost reductions (the
        ``OpponentsControlAtLeast(IsCreature(), 3)`` condition is
        True now — 3 opp creatures on bf — so the
        ``apply_cost_reductions`` helper at ``actions.py``
        returns ``ManaCost(generic=2, colored=(('G', 2),),
        x_pips=0)``), pays via ``auto_tap_for_cost`` (drains 2
        colorless + 2 green exactly), pushes the StackItem,
        increments ``spells_cast_this_turn``, fires IS_CAST.
      * **Rust.** ``cast_creature(lashwhip_id, 0)`` drives the
        full Rust cast pipeline: the in-process call at
        ``state_ops_cast.rs`` routes through
        ``apply_cost_reductions_rust(state, idx, printing,
        base)`` which evaluates the OpponentsControlAtLeast
        Condition variant by scanning every opponent's
        battlefield (``state_ops_legal.rs:788-825``), summing
        permanents whose ``card_types`` contains ``"Creature"``
        — 3 here — early-outs at ``found >= n`` (= 3), returns
        the reduced ``{2}{G}{G}`` ManaCost,
        ``auto_tap_pay_for_cost`` drains 2C + 2G from the
        pool, rehomes to the stack-source store, dispatches
        Event::Cast, pushes the StackItem.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack.

    Critical bytes the probe pins:
      * Pool empty on both post-cast (the reduced {2}{G}{G} was
        paid exactly — Rust did NOT silently pay through 4
        colorless the way the pre-Cycle-2 false-emission would
        have; both engines applied the SAME {2} reduction).
      * Lashwhip off hand, on stack on both.
      * 3 opponent creatures still on opp's battlefield (the
        scripted-picker pre-seat survives the cast unchanged).

    **This is the case that diverges pre-Phase-1** (per design
    doc §7.3 / §3 admit table). The Cycle-2 substrate landed the
    byte-equal arithmetic on both sides; this probe is the
    live-printing, actual-cast byte-equal proof on the
    battlefield-scanning Condition variant — exactly the
    "round-46 real-EoE-signal discipline" floor for the
    OpponentsControlAtLeast carrier.
    """
    from mtg_bot.actions import _cast_spell
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import ManaCoin, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    real = _PRINTINGS.get("Lashwhip Predator")
    if real is None:
        pytest.skip("Lashwhip Predator absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Scripted picker (design doc §7.3): seat 3 vanilla 2/2
    # Bear-shape creatures on opp's (p1's) battlefield on BOTH
    # engines in lockstep. These carry no cost_reductions, no
    # abilities, no keywords — pure type=Creature carriers that
    # satisfy the IsCreature filter in OpponentsControlAtLeast's
    # battlefield scan. The injection order (3 opp creatures
    # FIRST, then Lashwhip into p0's hand) keeps the per-zone
    # object_id allocation in lockstep across engines so the
    # cross-engine field-view comparison agrees on id slots.
    bear_printing = CardPrinting(
        name="Scripted Opp Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    py_opp_creatures: list = []
    for _ in range(3):
        py_b = py.new_object(
            bear_printing, owner_id=1, zone=Zone.BATTLEFIELD,
        )
        py_b.summoning_sick = False
        py_b.etb_timestamp = py.next_timestamp
        py.next_timestamp += 1
        py.battlefield.append(py_b)
        py_opp_creatures.append(py_b)

    rs_opp_creature_ids: list = []
    for _ in range(3):
        rs_b = rs.register_and_inject_object(
            {
                "name": "Scripted Opp Bear",
                "card_types": ["Creature"],
                "mana_cost": {"generic": 1, "G": 1},
                "power": 2,
                "toughness": 2,
            },
            1, 2,  # controller=1 (opp), zone=2 (BATTLEFIELD)
        )
        rs_opp_creature_ids.append(rs_b)

    # ---- Python: seat Lashwhip in p0's hand; prime p0's pool with
    # 2 colorless + 2 green (the reduced cost).
    py_l = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_l)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="G"),
        ManaCoin(color="G"),
    ])

    # ---- Rust: register Lashwhip-shape carrier in p0's hand;
    # prime p0's pool identically.
    rs_l = rs.register_and_inject_object(
        {
            "name": "Lashwhip Predator",
            "card_types": ["Creature"],
            "subtypes": ["Plant", "Beast"],
            "mana_cost": {"generic": 4, "G": 2},
            "power": 5,
            "toughness": 7,
            "cost_reductions": [
                {
                    "amount": 2,
                    "condition_kind": "opponents_control_at_least",
                    "condition_args": ("creature", 3),
                },
            ],
        },
        0, 0,  # zone 0 = HAND
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "G", 1)
    rs.add_mana(0, "G", 1)

    # Pre-cast sanity: 3 opp creatures on bf on both engines;
    # stack empty on both.
    assert len(py.battlefield) == 3
    assert all(o.controller_id == 1 for o in py.battlefield)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_l.id)
    ok = rs.cast_creature(rs_l, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Lashwhip Predator at "
        "REDUCED {2}{G}{G} cost (with 3 opp creatures on bf) "
        "with a {2}{G}{G}-primed pool — the {2} reduction MUST "
        "apply, and the apply_cost_reductions_rust helper MUST "
        "scan opp's bf, count 3 IsCreature matches, and return "
        "ManaCost(generic=2, G=2). If this fails as 'insufficient "
        "mana' it means the reduction did NOT fire — either the "
        "Cycle-2 substrate did not apply the Phase-1 cost "
        "reduction on the live printing, or the opponent-bf "
        "scan missed the seeded creatures."
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty: only {2}{G}{G} was paid (2 colorless + 2
    # green). If the reduction did NOT apply on Python somehow, the
    # cast would have failed at auto_tap_for_cost (insufficient
    # mana — we primed only 4 coins, not 6).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (reduced cost "
        f"{{2}}{{G}}{{G}} paid exactly); got "
        f"{py.players[0].mana_pool}. A non-empty pool here means "
        f"the reduction over-applied (paid less than expected); a "
        f"failed-cast path would surface at auto_tap_for_cost."
    )
    # Hand emptied; Lashwhip on the stack.
    assert all(o.id != py_l.id for o in py.players[0].hand)
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_l.id
    # Opp creatures unchanged on bf (3 still there post-cast — the
    # cost-payment scan is read-only).
    assert len(py.battlefield) == 3
    assert all(o.controller_id == 1 for o in py.battlefield)

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast (reduced cost paid "
        f"exactly); got {rs_pool}. A non-empty pool means the "
        f"reduction over-applied; a successful cast with a "
        f"non-empty pool would mean the Rust helper returned a "
        f"smaller cost than Python's apply_cost_reductions."
    )
    # Lashwhip on the stack. A successful cast with the {2}{G}{G}-
    # only primed pool is the load-bearing inline check: the Rust
    # helper MUST have scanned opp's bf, counted 3 IsCreature
    # matches, evaluated OpponentsControlAtLeast(IsCreature(), 3)
    # → True and returned the reduced {2}{G}{G}, otherwise
    # auto_tap_pay_for_cost would have short-spent at the {4}{G}{G}
    # base.
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Lashwhip Predator reduced-cost lifecycle (cast with 3 "
        f"opp creatures on bf — the {{2}} reduction applies) "
        f"must be byte-equal across the WHOLE field view on BOTH "
        f"engines; diffs={diffs}. This is the load-bearing "
        f"byte-equal that the Cycle-2 substrate FLIP rides on for "
        f"the OpponentsControlAtLeast carrier — a divergence "
        f"here is an honest-stop signal."
    )
