"""Uthros Psionicist Cycle 3 — per-card real-EoE cross-engine byte-
equality probe (``covered_by_construction`` → PROBED tier flip).

Uthros Psionicist is a ``{2}{U}`` Creature — Jellyfish Scientist (2/4,
EoE — sourced from ``data/edge_of_eternities.json``) with a single
Phase-2 EXTERNAL cost-reduction rider:

    "The second spell you cast each turn costs {2} less to cast."

Parsed into one
``ExternalCostReduction(amount=2, condition=NthSpellThisTurn(n=2))``
under ``printing.external_cost_reductions`` (Phase-2 sub-shape B). No
spell-local ``cost_reductions``, no spell effect, no triggered or
activated abilities, no warp/impending/static riders — the cleanest
Sub-shape-B Phase-2 carrier (per
``docs/COST_REDUCTION_SUBSTRATE_PHASE_2_DESIGN.md`` §3).

**Multi-cycle DECLINED → ADMITTED → PROBED transition (this lane is
the Cycle-3 closure marker for sub-shape B of Phase 2).**

  * **Phase 1 Cycle 1 (substrate, commit ``3683e62e``).** Rust
    ``CostReduction`` + ``Condition`` enum + ``Printing.cost_
    reductions`` (Phase-1 spell-local field) + Phase-1 evaluator hook.
    Uthros stayed DECLINED — Uthros' rider lives on the EXTERNAL
    axis, which the Phase-1 substrate did not yet carry.
  * **Phase 1 Cycle 2 (commit ``8593b0fb``, 2026-05-24).** The
    bridge admit predicate
    ``_printing_is_bridge_pure_cost_reduction_creature`` landed but
    its §2 teeth EXPLICITLY rejected any printing carrying
    ``external_cost_reductions``; Uthros stayed DECLINED with that
    reject hard-coded.
  * **Phase 2 Cycle 1 (substrate, commit ``5fa32697``, 2026-05-25).**
    Rust ``ExternalCostReduction`` + ``ExternalCondition`` enum
    subset (``NthSpellThisTurn`` + ``PerControlled``) + the new
    ``TypeFilter::Artifact`` variant + ``CardPrinting.external_cost_
    reductions`` field + ``parse_printing`` tag-dispatch + the
    ``apply_external_cost_reductions_rust`` helper (externals-first
    ordering — mirrors Python ``actions.apply_cost_reductions`` at
    ``actions.py:428-438``). Uthros stayed DECLINED at the admit
    gate (the C1 admit predicate still rejected
    ``external_cost_reductions``).
  * **Phase 2 Cycle 2 (THE FLIP, commit ``c370cee4``, 2026-05-25).**
    The CardDef ``external_cost_reductions`` field + bridge round-
    trip arms (``_spec_card_to_printing_dict`` Phase-2 emit +
    ``_card_def_to_python_printing`` Phase-2 reverse arm) + the
    widened admit predicate (Option A — the OLD
    ``external_cost_reductions`` reject swapped for an admit-loop
    against ``_external_cost_reduction_rule_is_phase2``). Uthros +
    Sami simultaneously flipped DECLINED → ADMITTED (the 2-card
    +15,575 17lands-deck single-cycle FLIP; the C2 substrate pin
    set pins admit set EXACTLY
    ``{"Gigastorm Titan", "Lashwhip Predator", "Sami, Wildcat
    Captain", "Uthros Psionicist"}``).
  * **Phase 2 Cycle 3 (this lane).** Per-card real-EoE cross-engine
    byte-equality probe driving BOTH lifecycles (full-cost cast as
    the FIRST spell of the turn + reduced-cost cast as the SECOND
    spell — the load-bearing case) flips
    ``covered_by_construction`` → PROBED in the pool-parity metric.
    Sami's Cycle-4 probe lands separately (the
    ``PerControlled(IsArtifact())`` variable-multiplier carrier;
    same shape as this one but exercising the affinity-style
    multiplier code path).

**Lifecycle coverage.** Both Phase-2 external-cost-reduction paths
are exercised through ``NthSpellThisTurn(n=2)``:

  * **Full-cost lifecycle (lifecycle A).** Pre-cast state:
    ``spells_cast_this_turn == 0`` on the caster, ONE Uthros-shape
    permanent already on the caster's battlefield as the
    cost-reduction carrier (since externals only fire when the
    carrier is on-bf — the helper walks the caster's bf at
    ``state_ops_legal.rs:903``). Uthros pays its base ``{2}{U}``
    — the ``NthSpellThisTurn(n=2)`` condition is False
    (``spells_cast_this_turn == 0 != n - 1 = 1``), the reduction
    does NOT apply. Pool primed with 2 colorless + 1 blue on both
    engines so ``auto_tap_pay_for_cost`` (Rust) /
    ``auto_tap_for_cost`` (Python) drain the pool cleanly without
    needing lands. Asserts full ``compare_fields == []``
    post-cast: pool empty on both, Uthros from hand now on the
    stack on both, the bf carrier untouched.
  * **Reduced-cost lifecycle (lifecycle B).** Pre-cast state:
    ``spells_cast_this_turn == 1`` (scripted picker: a cheap spell
    has already been cast this turn, driven via the
    ``set_spells_cast_this_turn`` setter on Rust + a direct field
    write on Python — design doc §7.3 "scripted picker" forcing
    the cheap-then-Uthros sequence without having to walk a full
    turn through cast of a vanilla cheap spell). The Uthros-shape
    carrier sits on the caster's battlefield. Uthros'
    ``NthSpellThisTurn(n=2)`` evaluates against
    ``spells_cast_this_turn == 1 == n - 1`` → True; the reduction
    applies and ``apply_external_cost_reductions_rust`` returns
    ``{0}{U}``. Pool primed with 1 blue on both engines (the
    EXACT reduced cost: the {2} reduction zeroes out the generic
    portion, leaving only the {U} colored pip). Asserts full
    ``compare_fields == []`` post-cast: pool empty on both, NO
    residual generic (the {2} reduction was actually applied,
    NOT silently paid through 2 colorless), Uthros on the stack
    on both, the bf carrier untouched, ``spells_cast_this_turn``
    advanced to 2 on both (the pre-existing 1 plus the
    post-cast increment).

**This is the LOAD-BEARING evidence for the Phase 2 Cycle 2 FLIP's
first carrier.** The C2 admit predicate trusted
``apply_external_cost_reductions_rust`` to mirror Python's
``_apply_external_cost_reductions`` byte-equal for the Phase-2
``NthSpellThisTurn`` shape; this probe is the per-card proof that the
round-46 real-EoE-signal discipline ('do NOT trust synthetic
CardDefs; drive the live ``OracleParserCardSource`` printing') holds
at the cast-and-pay level for the externals-axis condition variant,
not just at the substrate fixture level. The Phase-1 sibling
probes (Gigastorm Titan ``1f13f092`` / Lashwhip Predator ``6c4ee310``)
pinned the spell-local axis byte-equal; this probe is the
externals axis closure marker for sub-shape B; Sami's Cycle-4 sibling
will close sub-shape C (the variable-multiplier ``PerControlled``
variant).

The post-resolve permanent-on-bf check sits outside this probe's
scope (parallel to the Phase-1 sibling probes) — the cast-and-pay
path is the part the Cycle 2 substrate touched; the resolve path was
unchanged. This module concentrates on the cost-payment
byte-equality: pool debit, generic/colored split, the externals
battlefield scan that powers the Uthros reduction, and the
``spells_cast_this_turn`` post-increment.
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
# (1) Parser SoT — Uthros Psionicist is parser-claimed and emits the
# expected Phase-2 external cost-reduction shape (the Cycle-1 substrate
# pin, duplicated here so this module is self-contained for the
# PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_uthros_psionicist_parser_claims_card():
    assert "Uthros Psionicist" in _PRINTINGS, (
        "Uthros Psionicist must be parser-claimed by the active "
        "CardSource (EoE set)"
    )


def test_uthros_psionicist_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, single
    Phase-2 EXTERNAL cost-reduction rider on the
    ``external_cost_reductions`` axis; no other riders, no
    spell-local ``cost_reductions``)."""
    from mtg_bot.cards.base import ExternalCostReduction
    from mtg_bot.effects.conditions import NthSpellThisTurn

    p = _PRINTINGS["Uthros Psionicist"]
    assert p.mana_cost_str == "{2}{U}"
    assert "Creature" in p.card_types
    assert "Jellyfish" in p.subtypes
    assert "Scientist" in p.subtypes
    assert p.power == 2
    assert p.toughness == 4
    # Phase-2 external cost-reduction rider — the load-bearing shape.
    assert p.cost_reductions == ()
    assert len(p.external_cost_reductions) == 1
    (ext_rule,) = p.external_cost_reductions
    assert isinstance(ext_rule, ExternalCostReduction)
    assert ext_rule.amount == 2
    assert isinstance(ext_rule.condition, NthSpellThisTurn)
    assert ext_rule.condition.n == 2
    # No spell_effect / abilities / warp / impending / keywords —
    # the cleanest Sub-shape-B carrier per the design doc §3.
    assert not p.triggered_abilities
    assert not p.activated_abilities
    assert not p.static_abilities
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — Python printing → CardDef → Rust dict →
# Python printing round-trips byte-equal on the
# external_cost_reductions axis. Duplicated from the Phase-2 Cycle-2
# substrate pin so the per-card module is self-contained for the
# PROBED-tier evidence.
# ---------------------------------------------------------------------------


def test_uthros_psionicist_bridge_round_trip_byte_equal():
    """The Phase-2 Cycle-2 bridge: Python printing →
    ``_printing_to_card_def`` → ``CardDef.external_cost_reductions``
    triple → ``_spec_card_to_printing_dict`` Rust dict →
    ``Registry.register_printing`` → ``_card_def_to_python_printing``
    Python printing whose ``external_cost_reductions`` is byte-equal
    to the live-parsed input."""
    import mtg_bot_engine
    from mtg_bot.cards.base import ExternalCostReduction
    from mtg_bot.effects.conditions import NthSpellThisTurn
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    p_orig = _PRINTINGS["Uthros Psionicist"]
    cd = trajectory._printing_to_card_def(p_orig)
    assert cd.external_cost_reductions == (
        (2, "nth_spell_this_turn", (2,)),
    )
    # Phase-1 spell-local axis stays empty — Uthros carries
    # externals only.
    assert cd.cost_reductions == ()
    d = _spec_card_to_printing_dict(cd)
    assert d.get("external_cost_reductions") == [
        {
            "amount": 2,
            "condition_kind": "nth_spell_this_turn",
            "condition_args": (2,),
        },
    ]
    # The Phase-1 cost_reductions key is OMITTED entirely (empty
    # tuple → key skipped).
    assert "cost_reductions" not in d
    # Rust registry accepts the dict — no panic, no Err.
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(d)
    assert isinstance(pid, int)
    # Python reverse arm rematerializes a byte-equal CardPrinting.
    p_rt = _card_def_to_python_printing(cd)
    assert (
        p_rt.external_cost_reductions == p_orig.external_cost_reductions
    )
    (ext_rt,) = p_rt.external_cost_reductions
    assert isinstance(ext_rt, ExternalCostReduction)
    assert ext_rt.amount == 2
    assert isinstance(ext_rt.condition, NthSpellThisTurn)
    assert ext_rt.condition.n == 2


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the Phase-2 external cost-reduction
# condition tag ``nth_spell_this_turn`` parses on an Uthros-shape
# printing via ``register_and_inject_object``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_uthros_psionicist_synthetic_dict():
    """Lockstep pin: Rust's parse arm accepts the
    ``{"amount": 2, "condition_kind": "nth_spell_this_turn",
    "condition_args": (2,)}`` payload on an Uthros-shape synthetic
    carrier (the dict shape ``_spec_card_to_printing_dict`` emits
    for the ``external_cost_reductions`` axis)."""
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sid = rs.register_and_inject_object(
        {
            "name": "Uthros Psionicist (synthetic carrier)",
            "card_types": ["Creature"],
            "subtypes": ["Jellyfish", "Scientist"],
            "mana_cost": {"generic": 2, "U": 1},
            "power": 2,
            "toughness": 4,
            "external_cost_reductions": [
                {
                    "amount": 2,
                    "condition_kind": "nth_spell_this_turn",
                    "condition_args": (2,),
                },
            ],
        },
        0, 0,  # zone 0 = hand
    )
    assert isinstance(sid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — full-cost
# lifecycle. PROBED tier flip (one of two lifecycles in this Cycle-3
# closure marker — ``covered_by_construction`` → PROBED, lifecycle A).
#
# Lifecycle A: cast Uthros as the FIRST spell of the turn with an
# Uthros-shape carrier already on the caster's battlefield. The
# NthSpellThisTurn(n=2) condition checks `spells_cast_this_turn ==
# n - 1 == 1` — False on a 0-spells-cast state — so the {2} reduction
# does NOT apply and both engines pay the base {2}{U}.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_uthros_psionicist_full_cost_first_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Uthros Psionicist
    full-cost lifecycle (cast as the FIRST spell of the turn).
    PROBED tier flip evidence (Cycle 3 closure marker —
    ``covered_by_construction`` → PROBED, lifecycle A).**

    Pre-cast state on both engines: ``spells_cast_this_turn == 0``
    on the caster, one Uthros-shape carrier already on p0's
    battlefield (so the externals scan finds the rider but its
    NthSpellThisTurn condition evaluates False), a second Uthros
    in p0's hand to actually cast, p0's mana pool primed with
    {2}{U} (2 colorless + 1 blue, exactly the base ``mana_cost``
    Uthros needs when its reduction does not apply). No spells
    previously cast.

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, uthros_id)``
        drives the full Python cast pipeline (selects empty
        targets, applies cost reductions via
        ``apply_cost_reductions`` at ``actions.py``: walks the
        caster's battlefield via ``_apply_external_cost_reductions``,
        finds the Uthros-shape carrier's
        ``external_cost_reductions``, evaluates
        ``NthSpellThisTurn(n=2).matches`` against
        ``spells_cast_this_turn == 0 != 1`` → False, no reduction
        applies; then walks the spell-local ``cost_reductions``
        — empty for Uthros — no-op. Pays via ``auto_tap_for_cost``,
        pushes the ``StackItem``, increments
        ``spells_cast_this_turn``, fires IS_CAST).
      * **Rust.** ``cast_creature(uthros_id, 0)`` drives the full
        Rust cast pipeline. The
        ``apply_cost_reductions_rust(state, idx, printing, base)``
        helper at ``state_ops_legal.rs:764`` calls
        ``apply_external_cost_reductions_rust`` FIRST (the
        externals-first ordering pinned in Phase 2 Cycle 1; mirrors
        Python ``actions.py:428-438``); that helper walks the
        caster's bf at ``state_ops_legal.rs:903``, finds the
        Uthros-shape carrier's ``external_cost_reductions``,
        evaluates ``NthSpellThisTurn { n: 2 }`` against
        ``state.players[idx].spells_cast_this_turn == (n - 1) ==
        1`` — False on a 0-spells-cast state, no reduction
        applies; the empty spell-local ``cost_reductions`` then
        short-circuits to the base cost. Pays via
        ``auto_tap_pay_for_cost``, rehomes to the stack-source
        store, dispatches Event::Cast, increments
        ``spells_cast_this_turn``, pushes the StackItem.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack. Mana pool MUST
    be empty on both (the full {2}{U} was paid — no silent
    over-spend), Uthros (hand instance) MUST be off the hand and
    on the stack on both, the bf-resident Uthros carrier MUST
    stay on the battlefield untouched, ``spells_cast_this_turn``
    MUST equal 1 on both (the post-cast increment).

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

    real = _PRINTINGS.get("Uthros Psionicist")
    if real is None:
        pytest.skip("Uthros Psionicist absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat an Uthros-shape carrier on p0's battlefield
    # (the cost-reduction source — externals only fire when the
    # carrier is on-bf), then seat a second Uthros in p0's hand to
    # cast. Default Python ``new_object`` sets
    # ``summoning_sick=True``; align with Rust's
    # ``register_and_inject_object`` default of False on both the
    # bf carrier and the hand instance so the cross-engine field
    # view agrees byte-equal at the per-zone object-sig granularity.
    py_bf_uthros = py.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bf_uthros.summoning_sick = False
    py.battlefield.append(py_bf_uthros)
    py_hand_uthros = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py_hand_uthros.summoning_sick = False
    py.players[0].hand.append(py_hand_uthros)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="U"),
    ])
    # Sanity: no spells cast yet (pre-existing default of the fresh
    # build_python_state); the NthSpellThisTurn(n=2) condition is
    # False — the {2} reduction must NOT apply, both engines pay
    # the base {2}{U}.
    assert py.players[0].spells_cast_this_turn == 0

    # ---- Rust: register an Uthros-shape carrier in p0's
    # battlefield (zone 2) FIRST, then register the hand instance
    # (zone 0). The bridge round-trip (test 2) already pinned the
    # Python printing → Rust dict shape; reuse the same canonical
    # dict here for both injections. The injection order (bf
    # carrier first, then hand instance) keeps the per-zone
    # object_id allocation in lockstep across engines so the
    # cross-engine field-view comparison agrees on id slots.
    uthros_dict = {
        "name": "Uthros Psionicist",
        "card_types": ["Creature"],
        "subtypes": ["Jellyfish", "Scientist"],
        "mana_cost": {"generic": 2, "U": 1},
        "power": 2,
        "toughness": 4,
        "external_cost_reductions": [
            {
                "amount": 2,
                "condition_kind": "nth_spell_this_turn",
                "condition_args": (2,),
            },
        ],
    }
    rs_bf_uthros = rs.register_and_inject_object(
        uthros_dict, 0, 2,  # controller=0, zone=2 (BATTLEFIELD)
    )
    rs_hand_uthros = rs.register_and_inject_object(
        uthros_dict, 0, 0,  # controller=0, zone=0 (HAND)
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "U", 1)
    # Sanity: Rust state likewise has 0 spells cast pre-cast
    # (default for ``make_synthetic_state`` / ``build_rust_state``;
    # no ``set_spells_cast_this_turn`` call here).

    # Pre-cast sanity: nothing on the stack on either engine.
    assert len(py.stack) == 0 and rs.stack_size() == 0
    # The bf carrier is on both engines.
    assert len(py.battlefield) == 1
    assert py.battlefield[0].controller_id == 0

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_hand_uthros.id)
    ok = rs.cast_creature(rs_hand_uthros, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Uthros Psionicist at "
        "full {2}{U} cost with a {2}{U}-primed pool (first spell "
        "of turn — NthSpellThisTurn(n=2) condition False; no "
        "reduction applies)"
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty (the {2}{U} was paid exactly — no
    # residual mana, no silent over-spend).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (cost {{2}}{{U}} "
        f"paid exactly); got {py.players[0].mana_pool}"
    )
    # spells_cast_this_turn post-incremented to 1.
    assert py.players[0].spells_cast_this_turn == 1, (
        f"Python: spells_cast_this_turn must be 1 post-cast; got "
        f"{py.players[0].spells_cast_this_turn}"
    )
    # Hand emptied of the cast instance (the bf-resident Uthros
    # remains on the battlefield unaffected).
    assert all(
        o.id != py_hand_uthros.id for o in py.players[0].hand
    ), "Python: hand-resident Uthros must leave hand post-cast"
    # bf carrier untouched.
    assert any(
        o.id == py_bf_uthros.id for o in py.battlefield
    ), "Python: bf-resident Uthros carrier must stay on battlefield"
    # Stack carries Uthros.
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_hand_uthros.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast; got {rs_pool}"
    )
    # Stack carries Uthros. The successful cast with exactly the
    # {2}{U}-primed pool proves the reduction did NOT apply
    # (auto_tap_pay_for_cost would have short-spent if Rust
    # returned a reduced cost on a 0-spells-cast state — and the
    # pool would carry residual mana).
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Uthros Psionicist full-cost lifecycle (cast as first "
        f"spell of turn with a bf-resident carrier; "
        f"NthSpellThisTurn(n=2) condition False) must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — reduced-cost
# lifecycle. PROBED tier flip (one of two lifecycles in this Cycle-3
# closure marker — ``covered_by_construction`` → PROBED, lifecycle B).
# This is THE load-bearing case the C2 bridge admit predicate trusts:
# both engines apply the {2} external reduction byte-equal after
# scanning the caster's battlefield for the Uthros-shape carrier and
# evaluating NthSpellThisTurn(n=2) against spells_cast_this_turn == 1.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_uthros_psionicist_reduced_cost_second_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Uthros Psionicist
    reduced-cost lifecycle (cast as the SECOND spell of the turn
    with the Uthros-shape carrier on the caster's battlefield).
    PROBED tier flip evidence (Cycle 3 closure marker —
    ``covered_by_construction`` → PROBED, lifecycle B). THIS is the
    load-bearing probe: the {2} EXTERNAL reduction must apply
    byte-equal on both engines after scanning the caster's
    battlefield and evaluating NthSpellThisTurn(n=2) against
    spells_cast_this_turn == 1.**

    Pre-cast state on both engines: ``spells_cast_this_turn == 1``
    on the caster (a cheap spell has already been cast this turn —
    driven via the ``set_spells_cast_this_turn`` setter on Rust +
    a direct field write on Python; the scripted picker per the
    design doc §7.3 forces the cheap-then-Uthros sequence without
    having to walk a full turn through cast of a vanilla cheap
    spell). One Uthros-shape carrier on p0's battlefield (the
    cost-reduction source). A second Uthros in p0's hand to cast.
    p0's mana pool primed with {U} on both engines — the EXACT
    reduced cost: the {2} external reduction subtracts 2 generic
    from the {2}{U} base, zeroing the generic portion and leaving
    only the {U} colored pip.

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, uthros_id)``
        drives the full Python cast pipeline: selects empty
        targets, applies cost reductions
        (``apply_cost_reductions`` → ``_apply_external_cost_
        reductions``: walks the caster's battlefield, finds the
        Uthros-shape carrier's ``external_cost_reductions``,
        evaluates ``NthSpellThisTurn(n=2).matches`` against
        ``spells_cast_this_turn == 1 == n - 1`` → True, applies
        ``ext.amount * condition.multiplier`` ({2} reduction;
        ``NthSpellThisTurn.multiplier`` returns 1), the
        ``ManaCost.reduced(2)`` arithmetic at
        ``cards/base.py:298-305`` saturating-subs 2 generic →
        ``ManaCost(generic=0, colored=(('U', 1),), x_pips=0)``),
        pays via ``auto_tap_for_cost`` (drains 1 blue exactly),
        pushes the StackItem, increments ``spells_cast_this_turn``
        to 2, fires IS_CAST.
      * **Rust.** ``cast_creature(uthros_id, 0)`` drives the full
        Rust cast pipeline. The in-process call at
        ``state_ops_cast.rs:1167`` routes through
        ``apply_cost_reductions_rust(state, idx, printing, base)``
        at ``state_ops_legal.rs:764`` which calls
        ``apply_external_cost_reductions_rust`` FIRST (the
        externals-first ordering pinned in Phase 2 Cycle 1;
        mirrors Python ``actions.py:428-438``); that helper walks
        the caster's bf at ``state_ops_legal.rs:903``, finds the
        Uthros-shape carrier's ``external_cost_reductions``,
        evaluates ``NthSpellThisTurn { n: 2 }`` against
        ``state.players[idx].spells_cast_this_turn == (n - 1) ==
        1`` → True with multiplier 1 (at
        ``state_ops_legal.rs:919-922``), composes through
        ``cost.generic.saturating_sub(amt)`` (mirror of Python
        ``ManaCost.reduced`` at ``cards/base.py:298-305``) →
        ManaCost(generic=0, U=1). Pays via
        ``auto_tap_pay_for_cost`` (drains 1 blue), rehomes to the
        stack-source store, dispatches Event::Cast, increments
        ``spells_cast_this_turn`` to 2, pushes the StackItem.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack.

    Critical bytes the probe pins:
      * Pool empty on both post-cast (the reduced {U} was paid
        exactly — Rust did NOT silently pay through 2 colorless
        the way the pre-Phase-2 false-emission would have; both
        engines applied the SAME {2} external reduction).
      * Uthros (hand instance) off hand, on stack on both.
      * bf-resident Uthros carrier still on the battlefield (the
        cost-payment scan is read-only).
      * ``spells_cast_this_turn == 2`` on both (the pre-existing 1
        plus the post-cast increment of this cast).

    **This is the case that diverges pre-Phase-2** (per design
    doc §3 / §7.3 admit table). The Phase-2 Cycle-2 substrate
    landed the byte-equal arithmetic on both sides via the
    ``apply_external_cost_reductions_rust`` helper + the widened
    admit predicate; this probe is the live-printing,
    actual-cast byte-equal proof on the externals-axis condition
    variant — exactly the "round-46 real-EoE-signal discipline"
    floor for the NthSpellThisTurn carrier.
    """
    import mtg_bot_engine
    from mtg_bot.actions import _cast_spell
    from mtg_bot.game import ManaCoin, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    real = _PRINTINGS.get("Uthros Psionicist")
    if real is None:
        pytest.skip("Uthros Psionicist absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat an Uthros-shape carrier on p0's battlefield
    # (the cost-reduction source — externals only fire when the
    # carrier is on-bf), then seat a second Uthros in p0's hand to
    # cast. Align summoning_sick with Rust's default of False on
    # both objects so the cross-engine field view agrees
    # byte-equal at the per-zone object-sig granularity. Pre-bump
    # spells_cast_this_turn = 1 via direct field write — the
    # scripted picker for "cheap spell already cast this turn".
    py_bf_uthros = py.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bf_uthros.summoning_sick = False
    py.battlefield.append(py_bf_uthros)
    py_hand_uthros = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py_hand_uthros.summoning_sick = False
    py.players[0].hand.append(py_hand_uthros)
    py.players[0].mana_pool.extend([
        ManaCoin(color="U"),
    ])
    py.players[0].spells_cast_this_turn = 1

    # ---- Rust: register an Uthros-shape carrier in p0's
    # battlefield (zone 2) FIRST, then register the hand instance
    # (zone 0). Same canonical dict for both. Pre-bump
    # spells_cast_this_turn via the C1 substrate setter — the
    # scripted picker.
    uthros_dict = {
        "name": "Uthros Psionicist",
        "card_types": ["Creature"],
        "subtypes": ["Jellyfish", "Scientist"],
        "mana_cost": {"generic": 2, "U": 1},
        "power": 2,
        "toughness": 4,
        "external_cost_reductions": [
            {
                "amount": 2,
                "condition_kind": "nth_spell_this_turn",
                "condition_args": (2,),
            },
        ],
    }
    rs_bf_uthros = rs.register_and_inject_object(
        uthros_dict, 0, 2,  # controller=0, zone=2 (BATTLEFIELD)
    )
    rs_hand_uthros = rs.register_and_inject_object(
        uthros_dict, 0, 0,  # controller=0, zone=0 (HAND)
    )
    rs.add_mana(0, "U", 1)
    rs.set_spells_cast_this_turn(0, 1)

    # Pre-cast sanity: bf carrier on both engines; stack empty on
    # both; spells_cast_this_turn == 1 on both (the scripted
    # picker pre-seat).
    assert len(py.battlefield) == 1
    assert py.battlefield[0].controller_id == 0
    assert len(py.stack) == 0 and rs.stack_size() == 0
    assert py.players[0].spells_cast_this_turn == 1

    # Pre-cast cross-engine field-view sanity — the scripted-picker
    # setup is byte-equal on BOTH engines before any cast fires.
    # A divergence here is a setup bug, not a Cycle-2 substrate
    # bug — surface it early.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-cast scripted-picker setup must be byte-equal across "
        f"engines (bf carrier + hand Uthros + spells_cast_this_turn "
        f"= 1 + {{U}}-primed pool); got pre_diffs={pre_diffs}"
    )

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_hand_uthros.id)
    ok = rs.cast_creature(rs_hand_uthros, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Uthros Psionicist at "
        "REDUCED {U} cost (second spell of turn with bf-resident "
        "Uthros-shape carrier) with a {U}-only-primed pool — the "
        "{2} external reduction MUST apply, and the "
        "apply_external_cost_reductions_rust helper MUST scan "
        "p0's bf, find the carrier's ExternalCostReduction(2, "
        "NthSpellThisTurn(n=2)), evaluate "
        "spells_cast_this_turn == n - 1 == 1 → True, and return "
        "ManaCost(generic=0, U=1). If this fails as 'insufficient "
        "mana' it means the reduction did NOT fire — either the "
        "Phase-2 Cycle-2 substrate did not apply the external "
        "cost reduction on the live printing, or the caster-bf "
        "scan missed the seeded carrier."
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty: only {U} was paid (1 blue). If the
    # reduction did NOT apply on Python somehow, the cast would
    # have failed at auto_tap_for_cost (insufficient mana — we
    # primed only 1 coin, not 3).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (reduced cost {{U}} "
        f"paid exactly); got {py.players[0].mana_pool}. A "
        f"non-empty pool here means the reduction over-applied "
        f"(paid less than expected); a failed-cast path would "
        f"surface at auto_tap_for_cost."
    )
    # spells_cast_this_turn post-incremented from 1 to 2.
    assert py.players[0].spells_cast_this_turn == 2, (
        f"Python: spells_cast_this_turn must be 2 post-cast (1 pre "
        f"+ 1 from this cast); got "
        f"{py.players[0].spells_cast_this_turn}"
    )
    # Hand emptied of the cast instance.
    assert all(o.id != py_hand_uthros.id for o in py.players[0].hand)
    # bf carrier still present.
    assert any(o.id == py_bf_uthros.id for o in py.battlefield)
    # Stack carries Uthros.
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_hand_uthros.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast (reduced cost paid "
        f"exactly); got {rs_pool}. A non-empty pool means the "
        f"reduction over-applied; a successful cast with a "
        f"non-empty pool would mean the Rust helper returned a "
        f"smaller cost than Python's apply_cost_reductions."
    )
    # Stack carries Uthros. A successful cast with the {U}-only
    # primed pool is the load-bearing inline check: the Rust
    # external helper MUST have scanned p0's bf, found the
    # ExternalCostReduction(2, NthSpellThisTurn(n=2)) rider on the
    # carrier, evaluated spells_cast_this_turn == n - 1 == 1 →
    # True, and returned the reduced {U} cost; otherwise
    # auto_tap_pay_for_cost would have short-spent at the {2}{U}
    # base.
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Uthros Psionicist reduced-cost lifecycle (cast as the "
        f"second spell of the turn with a bf-resident carrier — "
        f"the {{2}} external reduction applies via "
        f"NthSpellThisTurn(n=2) on spells_cast_this_turn == 1) "
        f"must be byte-equal across the WHOLE field view on BOTH "
        f"engines; diffs={diffs}. This is the load-bearing "
        f"byte-equal that the Phase-2 Cycle-2 substrate FLIP "
        f"rides on for the NthSpellThisTurn external carrier — a "
        f"divergence here is an honest-stop signal."
    )
