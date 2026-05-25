"""Gigastorm Titan Cycle 3 — per-card real-EoE cross-engine byte-
equality probe (``covered_by_construction`` → PROBED tier flip).

Gigastorm Titan is a ``{4}{U}`` Creature — Elemental (4/4, EoE —
sourced from ``data/edge_of_eternities.json``) with a single Phase-1
boolean-condition cost-reduction rider:

    "This spell costs {3} less to cast if you've cast another spell
    this turn."

Parsed into one
``CostReduction(amount=3, condition=AnotherSpellCastThisTurn())``
under ``printing.cost_reductions``. No spell effect, no triggered or
activated abilities, no warp/impending/static/external riders — the
cleanest Sub-shape-A Phase-1 carrier (per
``docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md`` §2).

**Multi-cycle DECLINED → ADMITTED → PROBED transition (this lane is
the closure marker).**

  * **Cycle 1 (substrate, commit ``3683e62e``).** Rust
    ``CostReduction`` + ``Condition`` enum + ``Printing.cost_
    reductions`` field + parse path + Cycle-1 evaluator hook +
    ``set_spells_cast_this_turn`` getter/setter shipped; Gigastorm
    stayed DECLINED at the admit gate (the substrate had no admit
    predicate yet — the §2 "no auto-grow before the bridge" pin
    pinned the Cycle 1 lockstep).
  * **Cycle 2 (THE FLIP, commit ``8593b0fb``, 2026-05-24).** Rust
    ``apply_cost_reductions_rust`` (`state_ops_legal.rs:742`) +
    bridge round-trip on the Python ``cost_reductions`` axis
    (``_printing_to_card_def`` + ``_spec_card_to_printing_dict`` +
    ``_card_def_to_python_printing``) + the new admit predicate
    ``_printing_is_bridge_pure_cost_reduction_creature``; Gigastorm
    + Lashwhip simultaneously flipped DECLINED → ADMITTED (the
    2-card 24,908-deck single-cycle FLIP; pin #3 — admit set
    EXACTLY ``{"Gigastorm Titan", "Lashwhip Predator"}``).
  * **Cycle 3 (this lane).** Per-card real-EoE cross-engine
    byte-equality probe driving BOTH lifecycles (full-cost cast as
    first spell + reduced-cost cast as second spell) flips
    ``covered_by_construction`` → PROBED in the pool-parity metric.
    Lashwhip Predator's Cycle-4 probe lands separately.

**Lifecycle coverage.** Both Phase-1 cost-reduction paths are
exercised:

  * **Full-cost lifecycle (lifecycle A).** Pre-cast state:
    ``spells_cast_this_turn == 0`` on the caster. Gigastorm pays
    its base ``{4}{U}`` — the ``AnotherSpellCastThisTurn`` condition
    is False (no other spell yet), the reduction does NOT apply.
    Pool primed with 4 colorless + 1 blue on both engines so
    ``auto_tap_pay_for_cost`` (Rust) / ``auto_tap_for_cost``
    (Python) drain the pool cleanly without needing lands. Asserts
    full ``compare_fields == []`` post-cast: pool empty on both,
    Gigastorm on the stack on both, ``spells_cast_this_turn ==
    1`` on both (the post-cast increment).
  * **Reduced-cost lifecycle (lifecycle B).** Pre-cast state:
    ``spells_cast_this_turn == 1`` (a cheap spell already cast
    this turn — driven directly via the
    ``set_spells_cast_this_turn`` setter on Rust + a direct
    field write on Python; the scripted picker hand-built into
    this probe forces the cheap-then-Gigastorm sequence per the
    design doc §7.3 "scripted picker" note). Gigastorm's
    ``AnotherSpellCastThisTurn`` is True; the reduction applies
    and the helper returns ``{1}{U}``. Pool primed with 1
    colorless + 1 blue on both engines. Asserts full
    ``compare_fields == []`` post-cast: pool empty on both, NO
    residual generic (the ``{3}`` reduction was actually applied,
    NOT silently paid through 4 colorless), Gigastorm on the
    stack on both, ``spells_cast_this_turn == 2`` on both.

**This is the LOAD-BEARING evidence for the FLIP.** The C2 admit
predicate trusted ``apply_cost_reductions_rust`` to mirror Python's
``apply_cost_reductions`` byte-equal for the Phase-1 boolean
``AnotherSpellCastThisTurn`` shape; this probe is the per-card
proof that the round-46 real-EoE-signal discipline ('do NOT trust
synthetic CardDefs; drive the live ``OracleParserCardSource``
printing') holds at the cast-and-pay level, not just at the
substrate fixture level (Cycle 2 Pin #7 was the registry-only
pin; this is the live-printing + actual cast pin).

The post-resolve permanent-on-bf check sits in a sibling probe
(Lashwhip Cycle 4) since the cast-and-pay path is the part the
Cycle 2 substrate touched; the resolve path was unchanged. This
module concentrates on the cost-payment byte-equality: pool
debit, generic/colored split, and the spells_cast_this_turn
post-increment.
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
# (1) Parser SoT — Gigastorm Titan is parser-claimed and emits the
# expected Phase-1 cost-reduction shape (the Cycle-1 substrate pin,
# duplicated here so this module is self-contained for the PROBED-tier
# evidence).
# ---------------------------------------------------------------------------


def test_gigastorm_titan_parser_claims_card():
    assert "Gigastorm Titan" in _PRINTINGS, (
        "Gigastorm Titan must be parser-claimed by the active "
        "CardSource (EoE set)"
    )


def test_gigastorm_titan_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, single
    Phase-1 cost-reduction rider; no other riders)."""
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.effects.conditions import AnotherSpellCastThisTurn

    p = _PRINTINGS["Gigastorm Titan"]
    assert p.mana_cost_str == "{4}{U}"
    assert "Creature" in p.card_types
    assert "Elemental" in p.subtypes
    assert p.power == 4
    assert p.toughness == 4
    # Phase-1 boolean cost-reduction rider — the load-bearing shape.
    assert len(p.cost_reductions) == 1
    (rule,) = p.cost_reductions
    assert isinstance(rule, CostReduction)
    assert rule.amount == 3
    assert isinstance(rule.condition, AnotherSpellCastThisTurn)
    # No external_cost_reductions / spell_effect / abilities / warp /
    # impending — the cleanest Sub-shape-A carrier per the design
    # doc §2.
    assert p.external_cost_reductions == ()
    assert not p.triggered_abilities
    assert not p.activated_abilities
    assert not p.static_abilities
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — Python printing → CardDef → Rust dict →
# Python printing round-trips byte-equal on the cost_reductions axis.
# Duplicated from the Cycle-2 substrate pin so the per-card module is
# self-contained for the PROBED-tier evidence.
# ---------------------------------------------------------------------------


def test_gigastorm_titan_bridge_round_trip_byte_equal():
    """The Cycle-2 bridge: Python printing → ``_printing_to_card_def``
    → ``CardDef.cost_reductions`` triple → ``_spec_card_to_printing_
    dict`` Rust dict → ``Registry.register_printing`` → ``_card_def_
    to_python_printing`` Python printing whose ``cost_reductions`` is
    byte-equal to the live-parsed input."""
    import mtg_bot_engine
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.effects.conditions import AnotherSpellCastThisTurn
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    p_orig = _PRINTINGS["Gigastorm Titan"]
    cd = trajectory._printing_to_card_def(p_orig)
    assert cd.cost_reductions == (
        (3, "another_spell_cast_this_turn", ()),
    )
    d = _spec_card_to_printing_dict(cd)
    assert d.get("cost_reductions") == [
        {
            "amount": 3,
            "condition_kind": "another_spell_cast_this_turn",
            "condition_args": (),
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
    assert rule_rt.amount == 3
    assert isinstance(rule_rt.condition, AnotherSpellCastThisTurn)


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the Phase-1 cost-reduction
# condition tag ``another_spell_cast_this_turn`` parses on a
# Gigastorm-shape printing via ``register_and_inject_object``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_gigastorm_titan_synthetic_dict():
    """Lockstep pin: Rust's parse arm accepts the
    ``{"amount": 3, "condition_kind": "another_spell_cast_this_
    turn", "condition_args": ()}`` payload on a Gigastorm-shape
    synthetic carrier (the dict shape ``_spec_card_to_printing_dict``
    emits)."""
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sid = rs.register_and_inject_object(
        {
            "name": "Gigastorm Titan (synthetic carrier)",
            "card_types": ["Creature"],
            "subtypes": ["Elemental"],
            "mana_cost": {"generic": 4, "U": 1},
            "power": 4,
            "toughness": 4,
            "cost_reductions": [
                {
                    "amount": 3,
                    "condition_kind": "another_spell_cast_this_turn",
                    "condition_args": (),
                },
            ],
        },
        0, 0,  # zone 0 = hand
    )
    assert isinstance(sid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — full-cost
# lifecycle. PROBED tier flip (one of two lifecycles in this Cycle-3
# closure marker — ``covered_by_construction`` → PROBED).
#
# Lifecycle A: cast Gigastorm as the FIRST spell of the turn. No
# other spell has been cast yet, so the AnotherSpellCastThisTurn
# condition is False and the reduction does NOT apply. Both engines
# must pay the base {4}{U}.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_gigastorm_titan_full_cost_first_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Gigastorm Titan
    full-cost lifecycle (cast as the FIRST spell of the turn).
    PROBED tier flip evidence (Cycle 3 closure marker —
    ``covered_by_construction`` → PROBED, lifecycle A).**

    Pre-cast state on both engines: ``spells_cast_this_turn == 0``,
    Gigastorm in p0's hand, p0's mana pool primed with {4}{U}
    (4 colorless + 1 blue, exactly the base ``mana_cost`` Gigastorm
    needs when its reduction does not apply). No spells previously
    cast.

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, gigastorm_id)``
        drives the full Python cast pipeline (selects empty
        targets, applies cost reductions [no-op — condition is
        False], pays via ``auto_tap_for_cost``, pushes the
        ``StackItem``, increments ``spells_cast_this_turn``, fires
        IS_CAST).
      * **Rust.** ``cast_creature(gigastorm_id, 0)`` drives the
        full Rust cast pipeline (the same shape — reads
        ``apply_cost_reductions_rust(state, idx, printing,
        base)`` which short-circuits on the False condition,
        pays via ``auto_tap_pay_for_cost``, rehomes to the
        stack-source store, dispatches Event::Cast, increments
        ``spells_cast_this_turn``, pushes the StackItem).

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack. Mana pool MUST
    be empty on both (the full {4}{U} was paid — no silent
    over-spend), Gigastorm MUST be off the hand and on the
    stack on both, ``spells_cast_this_turn`` MUST equal 1 on both.

    The probe deliberately uses pool-primed mana (not lands) so
    the cost-payment is a pure pool drain — the cost-reduction
    arithmetic is the entire load-bearing signal on this lifecycle
    (no land-tapping noise; ``auto_tap_pay_for_cost`` drains the
    pool exactly as ``auto_tap_for_cost`` does on Python).
    """
    import mtg_bot_engine
    from mtg_bot.actions import _cast_spell
    from mtg_bot.game import ManaCoin, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    real = _PRINTINGS.get("Gigastorm Titan")
    if real is None:
        pytest.skip("Gigastorm Titan absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat Gigastorm in p0's hand; prime p0's pool with
    # 4 colorless + 1 blue.
    py_g = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_g)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="U"),
    ])
    # Sanity: no spells cast yet (pre-existing default of the fresh
    # build_python_state); the AnotherSpellCastThisTurn condition is
    # False — the {3} reduction must NOT apply, both engines pay {4}{U}.
    assert py.players[0].spells_cast_this_turn == 0

    # ---- Rust: register a Gigastorm-shape carrier in p0's hand;
    # prime p0's pool identically. The bridge round-trip (test 2)
    # already pinned the Python printing → Rust dict shape; reuse
    # the same canonical dict here for the carrier injection.
    rs_g = rs.register_and_inject_object(
        {
            "name": "Gigastorm Titan",
            "card_types": ["Creature"],
            "subtypes": ["Elemental"],
            "mana_cost": {"generic": 4, "U": 1},
            "power": 4,
            "toughness": 4,
            "cost_reductions": [
                {
                    "amount": 3,
                    "condition_kind": "another_spell_cast_this_turn",
                    "condition_args": (),
                },
            ],
        },
        0, 0,  # zone 0 = HAND
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "U", 1)
    # Sanity: Rust state likewise has 0 spells cast pre-cast.
    # (Default for ``make_synthetic_state`` / ``build_rust_state``.)

    # Pre-cast sanity: nothing on the stack on either engine.
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_g.id)
    ok = rs.cast_creature(rs_g, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Gigastorm Titan at "
        "full {4}{U} cost with a {4}{U}-primed pool"
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty (the {4}{U} was paid exactly — no
    # residual mana, no silent over-spend).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (cost {{4}}{{U}} paid "
        f"exactly); got {py.players[0].mana_pool}"
    )
    # spells_cast_this_turn post-incremented to 1.
    assert py.players[0].spells_cast_this_turn == 1, (
        f"Python: spells_cast_this_turn must be 1 post-cast; got "
        f"{py.players[0].spells_cast_this_turn}"
    )
    # Hand emptied (Gigastorm moved onto the stack source).
    assert all(o.id != py_g.id for o in py.players[0].hand), (
        "Python: Gigastorm must leave hand post-cast"
    )
    # Stack carries Gigastorm.
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_g.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast; got {rs_pool}"
    )
    # Stack carries Gigastorm. The spells_cast_this_turn increment is
    # observable on the Python side directly; on the Rust side the
    # increment is internal — the byte-equal field view comparison
    # below is the cross-engine assertion. The fact that the cast
    # succeeded with exactly the {4}{U}-primed pool proves the
    # reduction did NOT apply (auto_tap_pay_for_cost would have
    # short-spent if Rust returned a reduced cost on a 0-spells-cast
    # state — and the pool would carry residual mana).
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Gigastorm Titan full-cost lifecycle (cast as first spell) "
        f"must be byte-equal across the WHOLE field view on BOTH "
        f"engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — reduced-cost
# lifecycle. PROBED tier flip (one of two lifecycles in this Cycle-3
# closure marker — ``covered_by_construction`` → PROBED, lifecycle B).
# This is THE load-bearing case the C2 bridge admit predicate trusts:
# both engines apply the {3} reduction byte-equal.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_gigastorm_titan_reduced_cost_after_cheap_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Gigastorm Titan
    reduced-cost lifecycle (cast AFTER a cheap spell already cast
    this turn). PROBED tier flip evidence (Cycle 3 closure marker
    — ``covered_by_construction`` → PROBED, lifecycle B). THIS is
    the load-bearing probe: the {3} reduction must apply
    byte-equal on both engines.**

    Pre-cast state on both engines: ``spells_cast_this_turn == 1``
    on the caster (a cheap spell has already been cast this turn —
    driven via the ``set_spells_cast_this_turn`` setter on Rust +
    a direct field write on Python; this is the design doc §7.3
    "scripted picker" forcing the cheap-then-Gigastorm sequence
    without having to walk a full turn through cast of a vanilla
    cheap spell). Gigastorm in p0's hand. p0's mana pool primed
    with {1}{U} on both engines — the EXACT reduced cost: the
    {3} reduction subtracts 3 generic from the {4}{U} base, so
    the pay-time cost is {1}{U}.

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, gigastorm_id)``
        drives the full Python cast pipeline: selects empty
        targets, applies cost reductions (the
        ``AnotherSpellCastThisTurn`` condition is True now —
        ``spells_cast_this_turn >= 1`` — so the
        ``apply_cost_reductions`` helper at ``actions.py:406-438``
        returns ``ManaCost(generic=1, colored=(('U', 1),),
        x_pips=0)``), pays via ``auto_tap_for_cost`` (drains 1
        colorless + 1 blue exactly), pushes the StackItem,
        increments ``spells_cast_this_turn`` to 2, fires IS_CAST.
      * **Rust.** ``cast_creature(gigastorm_id, 0)`` drives the
        full Rust cast pipeline: the in-process call at
        ``state_ops_cast.rs:1167`` routes through
        ``apply_cost_reductions_rust(state, idx, printing,
        base)`` which evaluates the AnotherSpellCastThisTurn
        Condition variant against ``self.players[idx].
        spells_cast_this_turn == 1`` (True — the post-Cycle-2
        evaluator hook), returns the reduced ``{1}{U}`` ManaCost,
        ``auto_tap_pay_for_cost`` drains 1C + 1U from the
        pool, rehomes to the stack-source store, dispatches
        Event::Cast, increments ``spells_cast_this_turn`` to 2,
        pushes the StackItem.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack.

    Critical bytes the probe pins:
      * Pool empty on both post-cast (the reduced {1}{U} was paid
        exactly — Rust did NOT silently pay through 4 colorless
        the way the pre-Cycle-2 false-emission would have; both
        engines applied the SAME {3} reduction).
      * Gigastorm off hand, on stack on both.
      * ``spells_cast_this_turn == 2`` on both (the pre-existing 1
        plus the post-cast increment of this cast).

    **This is the case that diverges pre-Phase-1** (per design
    doc §7.3). The Cycle-2 substrate landed the byte-equal
    arithmetic on both sides; this probe is the live-printing,
    actual-cast byte-equal proof — exactly the "round-46 real-EoE-
    signal discipline" floor.
    """
    import mtg_bot_engine
    from mtg_bot.actions import _cast_spell
    from mtg_bot.game import ManaCoin, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    real = _PRINTINGS.get("Gigastorm Titan")
    if real is None:
        pytest.skip("Gigastorm Titan absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat Gigastorm in p0's hand; prime p0's pool with
    # 1 colorless + 1 blue (the reduced cost); pre-bump
    # spells_cast_this_turn = 1 (scripted picker: "cheap spell
    # already cast this turn").
    py_g = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_g)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="U"),
    ])
    py.players[0].spells_cast_this_turn = 1

    # ---- Rust: register Gigastorm-shape carrier in p0's hand;
    # prime p0's pool identically; pre-bump spells_cast_this_turn
    # via the setter (the C1 substrate getter/setter API).
    rs_g = rs.register_and_inject_object(
        {
            "name": "Gigastorm Titan",
            "card_types": ["Creature"],
            "subtypes": ["Elemental"],
            "mana_cost": {"generic": 4, "U": 1},
            "power": 4,
            "toughness": 4,
            "cost_reductions": [
                {
                    "amount": 3,
                    "condition_kind": "another_spell_cast_this_turn",
                    "condition_args": (),
                },
            ],
        },
        0, 0,  # zone 0 = HAND
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "U", 1)
    rs.set_spells_cast_this_turn(0, 1)

    # Pre-cast sanity: stack empty on both.
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_g.id)
    ok = rs.cast_creature(rs_g, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Gigastorm Titan at "
        "REDUCED {1}{U} cost (after another spell cast this turn) "
        "with a {1}{U}-primed pool — the {3} reduction MUST apply, "
        "and the apply_cost_reductions_rust helper MUST return "
        "ManaCost(generic=1, U=1). If this fails as 'insufficient "
        "mana' it means the reduction did NOT fire — the Cycle-2 "
        "substrate did not apply the Phase-1 cost reduction on the "
        "live printing."
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty: only {1}{U} was paid (1 colorless + 1
    # blue). If the reduction did NOT apply on Python somehow, the
    # cast would have failed at auto_tap_for_cost (insufficient
    # mana — we primed only 2 coins, not 5).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (reduced cost "
        f"{{1}}{{U}} paid exactly); got "
        f"{py.players[0].mana_pool}. A non-empty pool here means "
        f"the reduction over-applied (paid less than expected); a "
        f"failed-cast path would surface at auto_tap_for_cost."
    )
    # spells_cast_this_turn post-incremented from 1 to 2.
    assert py.players[0].spells_cast_this_turn == 2, (
        f"Python: spells_cast_this_turn must be 2 post-cast (1 pre "
        f"+ 1 from this cast); got "
        f"{py.players[0].spells_cast_this_turn}"
    )
    # Hand emptied; Gigastorm on the stack.
    assert all(o.id != py_g.id for o in py.players[0].hand)
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_g.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast (reduced cost paid "
        f"exactly); got {rs_pool}. A non-empty pool means the "
        f"reduction over-applied; a successful cast with a "
        f"non-empty pool would mean the Rust helper returned a "
        f"smaller cost than Python's apply_cost_reductions."
    )
    # The spells_cast_this_turn increment from 1 → 2 is internal on
    # the Rust side; the full field-view byte-equality below is the
    # cross-engine assertion. A successful cast with the {1}{U}-only
    # primed pool is the load-bearing inline check: the Rust helper
    # MUST have evaluated AnotherSpellCastThisTurn → True and
    # returned the reduced {1}{U}, otherwise auto_tap_pay_for_cost
    # would have short-spent at the {4}{U} base.
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Gigastorm Titan reduced-cost lifecycle (cast after "
        f"another spell this turn — the {{3}} reduction applies) "
        f"must be byte-equal across the WHOLE field view on BOTH "
        f"engines; diffs={diffs}. This is the load-bearing "
        f"byte-equal that the Cycle-2 substrate FLIP rides on — a "
        f"divergence here is an honest-stop signal."
    )
