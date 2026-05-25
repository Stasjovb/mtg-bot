"""Fungal Colossus Cycle 3 — per-card real-EoE cross-engine
byte-equality probe (``covered_by_construction`` → PROBED tier flip;
**THE FINAL probe of cost-reduction Phase 3 — and THE FINAL probe of
the entire cost-reduction substrate single-gated lane**).

Fungal Colossus is a ``{6}{G}`` Creature — Fungus Beast (5/5, EoE —
sourced from ``data/edge_of_eternities.json``) with a single Phase-3
spell-local cost-reduction rider on the variable-multiplier axis:

    "This spell costs {X} less to cast, where X is the number of
    differently named lands you control."

Parsed into one
``CostReduction(amount=1, condition=PerDifferentlyNamedLand())`` under
``printing.cost_reductions`` (Phase-3 sub-shape D — the unit-shape
variable-X spell-local path; the multiplier is the count of distinctly-
named lands the caster controls). No spell-local externals, no spell
effect, no triggered or activated abilities, no warp/impending/static
riders, no keywords — the cleanest Sub-shape-D Phase-3 carrier (per
``docs/COST_REDUCTION_SUBSTRATE_PHASE_3_DESIGN.md`` §2).

**Multi-cycle DECLINED → ADMITTED → PROBED transition (this lane is
the closure marker for Phase 3 — and the LAST closure marker of the
entire cost-reduction substrate campaign).**

  * **Phase 1 Cycle 1 (substrate, commit ``3683e62e``).** Rust
    ``CostReduction`` + ``Condition`` enum + ``Printing.cost_
    reductions`` (Phase-1 spell-local field) + Phase-1 evaluator hook.
    Fungal stayed DECLINED — Fungal's rider lives on a
    variable-multiplier condition variant (``PerDifferentlyNamedLand``)
    that the Phase-1 substrate did not yet carry.
  * **Phase 1 Cycle 2 (commit ``8593b0fb``, 2026-05-24).** The bridge
    admit predicate ``_printing_is_bridge_pure_cost_reduction_creature``
    landed but its admit-loop walked only Phase-1 conditions; Fungal
    stayed DECLINED.
  * **Phase 2 Cycle 1 + 2 (commits ``5fa32697`` + ``c370cee4``,
    2026-05-25).** Externals substrate + admit-widen for the
    ``external_cost_reductions`` axis (sub-shapes B + C). Fungal's
    rider lives on the spell-local ``cost_reductions`` axis with a
    variable-multiplier condition the externals substrate does not
    carry — Fungal stayed DECLINED.
  * **Phase 3 Cycle 1 (substrate, commit ``8525d18e``, 2026-05-25).**
    Rust ``Condition::PerDifferentlyNamedLand`` unit-shape variant
    + ``unique_land_names_count`` helper (HashSet<&str> over
    ``printing.name``, filtered by ``card_types`` contains-"Land") +
    ``apply_cost_reductions_rust`` spell-local match arm extended to
    the ``(holds, multiplier)`` pair shape Phase-2 externals
    established (the FIRST variable-multiplier on the spell-local
    axis — Phase-1 boolean variants kept implicit multiplier=1;
    Phase-3 variant returns ``(count >= 1, count)``). Fungal stayed
    DECLINED at the admit gate (the C1 admit predicate still walked
    only the Phase-1 condition list).
  * **Phase 3 Cycle 2 (THE FLIP, commit ``7036c191``, 2026-05-25).**
    Bridge reverse-arm extension (``per_differently_named_land`` elif
    in ``_card_def_to_python_printing``) + widened admit helper
    ``_cost_reduction_rule_is_phase1_or_3`` (Option A — renamed from
    ``_cost_reduction_rule_is_phase1`` with a
    ``PerDifferentlyNamedLand`` admit arm appended) + forward-emit
    arm in ``_printing_to_card_def`` producing the wire triple
    ``(amount, "per_differently_named_land", ())`` + CardDef
    ``cost_reductions`` field docstring update. Fungal Colossus
    DECLINED → ADMITTED at the bridge admit gate (admit set
    4 → 5 cards; cost-reduction substrate single-gated row 1 → 0;
    BLOCKED 56 → 55 — the cost-reduction substrate retires from the
    single-gated rollup entirely).
  * **Phase 3 Cycle 3 (THIS LANE; the FINAL probe of Phase 3 — and
    the FINAL probe of the entire cost-reduction substrate campaign).**
    Per-card real-EoE cross-engine byte-equality probe driving BOTH
    engines through 3 scenarios across the variable-X land-count
    range — the multiplier-axis exhaust — flips
    ``covered_by_construction`` → PROBED in the pool-parity metric.
    Fungal is the ONLY Phase-3 cost-reduction carrier; with this
    commit, the cost-reduction substrate retires from
    ``covered_by_construction`` entirely. ~13,165 17lands decks
    attributable to Fungal Colossus per the design doc per-card
    breakdown.

**Lifecycle coverage — THREE scenarios across the variable-X path.**
``PerDifferentlyNamedLand`` is the FIRST spell-local
variable-multiplier ``Condition`` variant; the multiplier IS the count
of distinctly-named caster-controlled lands (per
``effects/conditions.py:391-402`` Python / ``state_ops_legal.rs:
870-893`` Rust — the ``unique_land_names_count`` set-semantic walk).
The three scenarios exhaust the load-bearing arithmetic surface:

  * **Scenario (a) — 0 lands → full ``{6}{G}`` both seats
    (multiplier=0; ``count >= 1`` is False → vacuously 0 reduction).**
    Pre-cast state: ONE Fungal in p0's hand to cast, ZERO lands on
    either battlefield. Fungal's ``PerDifferentlyNamedLand`` walks
    p0's bf for distinctly-named lands — set is empty, ``count ==
    0 < 1``, condition False; the reduction does NOT apply. Pool
    primed with ``{6}{G}`` (6 colorless + 1 green, the EXACT base
    cost). Asserts ``compare_fields == []`` post-cast: pool empty
    on both, Fungal off hand and on the stack on both.
  * **Scenario (b) — 4 distinctly-named lands → reduced ``{2}{G}``
    both seats (multiplier=4; the set-semantic distinct path —
    the load-bearing case).** Pre-cast state: ONE Fungal in p0's
    hand to cast, FOUR distinctly-named EoE-land permanents
    pre-seated on p0's battlefield via the scripted picker —
    ``register_and_inject_object`` on Rust (controller=0,
    zone=ZONE_BATTLEFIELD) + ``new_object`` + ``state.battlefield.
    append`` on Python (owner_id=0, zone=Zone.BATTLEFIELD). The
    four chosen lands (Breeding Pool / Godless Shrine / Command
    Bridge / Adagia, Windswept Bastion) are real EoE-pool lands
    pulled from the active CardSource on Python; on Rust their
    same names are injected as bare ``card_types=["Land"]``
    synthetics (the ``unique_land_names_count`` walk keys ONLY on
    ``printing.name`` — Land-shape minimality is sufficient).
    Fungal's ``PerDifferentlyNamedLand`` walks p0's bf, the
    HashSet<&str> over land-printing names collects 4 distinct
    keys, ``count == 4 >= 1`` is True; ``multiplier == 4``. The
    reduction applies and ``apply_cost_reductions_rust`` returns
    ``ManaCost(generic=2, G=1)`` (the {1} amount times
    multiplier-of-4 = {4} of generic dropped from the {6}{G}
    base). Pool primed with 2 colorless + 1 green on both engines
    (the EXACT reduced cost). Asserts ``compare_fields == []``
    post-cast: pool empty on both, NO residual generic, Fungal
    on the stack on both, the 4 seated lands still on p0's bf
    unchanged.
  * **Scenario (c) — 4 same-named lands → reduced ``{5}{G}`` both
    seats (multiplier=1; the set-semantic edge case where 4 copies
    of the same land collapse to a single distinct name).**
    Pre-cast state: ONE Fungal in p0's hand to cast, FOUR copies
    of the SAME EoE land (Breeding Pool ×4) pre-seated on p0's
    battlefield. Fungal's ``PerDifferentlyNamedLand`` walks p0's
    bf — 4 land permanents, but the HashSet<&str> over
    ``printing.name`` collapses all 4 to a single ``"Breeding
    Pool"`` key, ``count == 1 >= 1`` is True, ``multiplier == 1``.
    The reduction applies and returns ``ManaCost(generic=5, G=1)``
    (the {1} amount times multiplier-of-1 = {1} of generic
    dropped from the {6}{G} base). Pool primed with 5 colorless +
    1 green on both engines (the EXACT reduced cost). This is the
    set-semantic teeth: a naive "count caster's lands" implementation
    would multiply by 4 and return ``{2}{G}`` (the same as
    scenario (b)) — the assertion proves both engines key the
    multiplier on the DISTINCT-NAME set, not the raw land count.
    Asserts ``compare_fields == []`` post-cast: pool empty on both
    (the {1} reduction was actually applied as ``amount *
    multiplier`` with multiplier=1, NOT the raw-count
    multiplier=4), Fungal on the stack on both, the 4 same-named
    lands still on p0's bf unchanged.

**This is the LOAD-BEARING evidence for the Phase 3 Cycle 2 FLIP and
the closure marker for the entire cost-reduction substrate
single-gated lane.** The C2 admit predicate trusted
``apply_cost_reductions_rust`` to mirror Python's
``apply_cost_reductions`` byte-equal for the
``PerDifferentlyNamedLand`` spell-local variable-multiplier shape;
this probe is the per-card proof that the round-46 real-EoE-signal
discipline ('do NOT trust synthetic CardDefs; drive the live
``OracleParserCardSource`` printing') holds at the cast-and-pay level
for the variable-X spell-local condition variant, not just at the
substrate fixture level. The Phase-1 sibling probes (Gigastorm Titan
``1f13f092`` / Lashwhip Predator ``6c4ee310``) pinned the spell-local
BOOLEAN axis byte-equal; the Phase-2 sibling probes (Uthros
Psionicist ``809d546c`` / Sami, Wildcat Captain) pinned the externals
axis byte-equal across both NthSpellThisTurn (implicit-1) and
PerControlled (variable-multiplier) sub-shapes. This probe completes
the matrix: the spell-local VARIABLE-MULTIPLIER axis byte-equal AND
the set-semantic distinct-name teeth on the multiplier-1 edge case —
together with the prior probes, the four cost-reduction axes
(spell-local boolean × externals boolean × externals variable ×
spell-local variable) are pinned byte-equal across the
ExternalCondition/Condition variant surface AND the
``amount * multiplier`` arithmetic on every live EoE carrier.

The post-resolve permanent-on-bf check sits outside this probe's
scope (parallel to all sibling probes) — the cast-and-pay path is
the part the Cycle 1+2 substrate touched; the resolve path was
unchanged. This module concentrates on the cost-payment byte-equality:
pool debit, generic/colored split, the spell-local battlefield scan
that powers the Fungal reduction via the unique-land-names HashSet,
and the amount-times-multiplier arithmetic on the variable-multiplier
spell-local path across all three multiplier values (0 / 1 / 4).
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


# The canonical Rust dict for the Fungal Colossus carrier — used by
# the cross-engine probes below + the rust-parse smoke. Mirrors the
# wire shape ``_spec_card_to_printing_dict`` emits for the Phase-3
# ``cost_reductions`` axis.
_FUNGAL_RUST_DICT = {
    "name": "Fungal Colossus",
    "card_types": ["Creature"],
    "subtypes": ["Fungus", "Beast"],
    "mana_cost": {"generic": 6, "G": 1},
    "power": 5,
    "toughness": 5,
    "cost_reductions": [
        {
            "amount": 1,
            "condition_kind": "per_differently_named_land",
            "condition_args": (),
        },
    ],
}

# Four real EoE-pool lands with DISTINCT names — used by scenario (b).
# Pulled from the live ``OracleParserCardSource``; the cross-engine
# probes seat the SAME four names on both engines (Python uses the
# real CardPrinting; Rust uses a bare ``card_types=["Land"]``
# synthetic since the ``unique_land_names_count`` walk keys ONLY on
# ``printing.name``).
_FOUR_DISTINCT_LAND_NAMES = (
    "Breeding Pool",
    "Godless Shrine",
    "Command Bridge",
    "Adagia, Windswept Bastion",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT — Fungal Colossus is parser-claimed and emits the
# expected Phase-3 spell-local cost-reduction shape (the Cycle-1
# substrate pin, duplicated here so this module is self-contained for
# the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_fungal_colossus_parser_claims_card():
    assert "Fungal Colossus" in _PRINTINGS, (
        "Fungal Colossus must be parser-claimed by the active "
        "CardSource (EoE set)"
    )


def test_fungal_colossus_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, single
    Phase-3 spell-local cost-reduction rider on the
    ``cost_reductions`` axis with the unit-shape variable-multiplier
    condition; no other riders, no externals, no keywords, no
    abilities, no warp/impending/spell_effect)."""
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand

    p = _PRINTINGS["Fungal Colossus"]
    assert p.mana_cost_str == "{6}{G}"
    assert "Creature" in p.card_types
    assert "Land" not in p.card_types, (
        "Fungal must NOT be Land-typed — the carrier must not "
        "self-count as a 'differently-named land'."
    )
    assert "Fungus" in p.subtypes
    assert "Beast" in p.subtypes
    assert p.power == 5
    assert p.toughness == 5
    # Phase-3 spell-local cost-reduction rider — the load-bearing shape.
    assert p.external_cost_reductions == ()
    assert len(p.cost_reductions) == 1
    (rule,) = p.cost_reductions
    assert isinstance(rule, CostReduction)
    assert rule.amount == 1
    assert isinstance(rule.condition, PerDifferentlyNamedLand)
    # No spell_effect / abilities / warp / impending / keywords — the
    # cleanest Sub-shape-D carrier per the design doc §2.
    assert not p.triggered_abilities
    assert not p.activated_abilities
    assert not p.static_abilities
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — Python printing → CardDef → Rust dict →
# Python printing round-trips byte-equal on the cost_reductions axis.
# Duplicated from the Phase-3 Cycle-2 substrate pin so the per-card
# module is self-contained for the PROBED-tier evidence.
# ---------------------------------------------------------------------------


def test_fungal_colossus_bridge_round_trip_byte_equal():
    """The Phase-3 Cycle-2 bridge: Python printing →
    ``_printing_to_card_def`` → ``CardDef.cost_reductions`` triple →
    ``_spec_card_to_printing_dict`` Rust dict →
    ``Registry.register_printing`` → ``_card_def_to_python_printing``
    Python printing whose ``cost_reductions`` is byte-equal to the
    live-parsed input."""
    import mtg_bot_engine
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    p_orig = _PRINTINGS["Fungal Colossus"]
    cd = trajectory._printing_to_card_def(p_orig)
    assert cd.cost_reductions == (
        (1, "per_differently_named_land", ()),
    )
    # Phase-2 externals axis stays empty — Fungal carries spell-local
    # only.
    assert cd.external_cost_reductions == ()
    d = _spec_card_to_printing_dict(cd)
    assert d.get("cost_reductions") == [
        {
            "amount": 1,
            "condition_kind": "per_differently_named_land",
            "condition_args": (),
        },
    ]
    # The Phase-2 external_cost_reductions key is OMITTED entirely
    # (empty tuple → key skipped).
    assert "external_cost_reductions" not in d
    # Rust registry accepts the dict — no panic, no Err.
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(d)
    assert isinstance(pid, int)
    # Python reverse arm rematerializes a byte-equal CardPrinting.
    p_rt = _card_def_to_python_printing(cd)
    assert p_rt.cost_reductions == p_orig.cost_reductions
    (rule_rt,) = p_rt.cost_reductions
    assert isinstance(rule_rt, CostReduction)
    assert rule_rt.amount == 1
    assert isinstance(rule_rt.condition, PerDifferentlyNamedLand)


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the Phase-3 spell-local
# cost-reduction condition tag ``per_differently_named_land`` parses
# on a Fungal-shape printing via ``register_and_inject_object``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_fungal_colossus_synthetic_dict():
    """Lockstep pin: Rust's parse arm accepts the
    ``{"amount": 1, "condition_kind": "per_differently_named_land",
    "condition_args": ()}`` payload on a Fungal-shape synthetic
    carrier (the dict shape ``_spec_card_to_printing_dict`` emits
    for the ``cost_reductions`` axis of Sub-shape D — the
    unit-shape variable-X ``PerDifferentlyNamedLand`` variant)."""
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sid = rs.register_and_inject_object(_FUNGAL_RUST_DICT, 0, 0)
    assert isinstance(sid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — scenario (a):
# 0 lands → full ``{6}{G}`` both seats (multiplier=0; condition holds
# vacuously False → 0 reduction). PROBED tier flip (one of three
# scenarios in this Cycle-3 closure marker — ``covered_by_construction``
# → PROBED, multiplier=0).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_fungal_colossus_full_cost_zero_lands_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Fungal Colossus
    full-cost scenario (cast with ZERO lands controlled). PROBED
    tier flip evidence (Cycle 3 closure marker —
    ``covered_by_construction`` → PROBED, scenario (a) — multiplier=0).**

    Pre-cast state on both engines: ONE Fungal in p0's hand to cast,
    ZERO lands on either battlefield (the distinct-name set is
    empty, ``count == 0 < 1``, condition False), p0's mana pool
    primed with ``{6}{G}`` (6 colorless + 1 green, EXACTLY the base
    ``mana_cost`` Fungal needs when its reduction does not apply).

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, fungal_id)``
        drives the full Python cast pipeline (selects empty
        targets, applies cost reductions via
        ``apply_cost_reductions`` at ``actions.py``: walks the
        spell-local ``cost_reductions``, finds the
        ``PerDifferentlyNamedLand`` rider, walks ``state.
        battlefield`` filtered to ``o.controller_id == viewer_id and
        o.printing.is_land`` — 0 land permanents found, ``count ==
        0 < 1`` → False — no reduction applies; the empty externals
        axis short-circuits to the base cost. Pays via
        ``auto_tap_for_cost``, pushes the ``StackItem``, increments
        ``spells_cast_this_turn``, fires IS_CAST).
      * **Rust.** ``cast_creature(fungal_id, 0)`` drives the full
        Rust cast pipeline. The
        ``apply_cost_reductions_rust(state, idx, printing, base)``
        helper at ``state_ops_legal.rs:764`` calls
        ``apply_external_cost_reductions_rust`` FIRST (externals-
        first ordering pinned in Phase 2 Cycle 1; mirrors Python
        ``actions.py:428-438``) — Fungal has no externals so the
        helper short-circuits — then walks the spell-local
        ``cost_reductions``, matches the
        ``Condition::PerDifferentlyNamedLand`` arm at
        ``state_ops_legal.rs:870-893``, calls
        ``unique_land_names_count(state, caster_idx)`` which walks
        ``state.players[0].battlefield`` with a ``HashSet<&str>``
        over ``printing.name`` filtered by ``card_types`` contains-
        "Land" — set is empty, returns 0 — ``(count >= 1, count) ==
        (false, 0)``, no reduction applies, short-circuits to the
        base cost. Pays via ``auto_tap_pay_for_cost``, rehomes to
        the stack-source store, dispatches Event::Cast, increments
        ``spells_cast_this_turn``, pushes the StackItem.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack. Mana pool MUST
    be empty on both (the full ``{6}{G}`` was paid — no silent
    over-spend), Fungal MUST be off the hand and on the stack on
    both.

    The probe deliberately uses pool-primed mana (not lands) so
    the cost-payment is a pure pool drain — the cost-reduction
    arithmetic is the entire load-bearing signal on this scenario
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

    real = _PRINTINGS.get("Fungal Colossus")
    if real is None:
        pytest.skip("Fungal Colossus absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat Fungal in p0's hand (no battlefield lands —
    # the variable-multiplier condition's land-name set is empty,
    # ``count >= 1`` False, no reduction applies). Default Python
    # ``new_object`` sets ``summoning_sick=True``; align with Rust's
    # ``register_and_inject_object`` default of False on the hand
    # instance so the cross-engine field view agrees byte-equal at
    # the per-zone object-sig granularity.
    py_fc = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py_fc.summoning_sick = False
    py.players[0].hand.append(py_fc)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="G"),
    ])
    # Sanity: no lands on either battlefield (the
    # PerDifferentlyNamedLand condition is False — count == 0 < 1
    # — the {1}-per-distinct-land reduction must NOT apply, both
    # engines pay the base {6}{G}).
    assert not any(
        "Land" in (o.printing.card_types or ()) for o in py.battlefield
    )

    # ---- Rust: register a Fungal-shape carrier in p0's hand (zone 0)
    # via the canonical dict pinned by the bridge round-trip in test 2.
    rs_fc = rs.register_and_inject_object(_FUNGAL_RUST_DICT, 0, 0)
    for _ in range(6):
        rs.add_mana(0, "C", 1)
    rs.add_mana(0, "G", 1)

    # Pre-cast sanity: nothing on the stack on either engine, no
    # lands anywhere.
    assert len(py.stack) == 0 and rs.stack_size() == 0
    assert len(py.battlefield) == 0

    # Pre-cast cross-engine field-view sanity — the setup is
    # byte-equal on BOTH engines before any cast fires. Divergence
    # here would be a setup bug, not a Cycle-1+2 substrate bug.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-cast 0-lands setup must be byte-equal across engines "
        f"(empty battlefield + hand Fungal + {{6}}{{G}}-primed "
        f"pool); got pre_diffs={pre_diffs}"
    )

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_fc.id)
    ok = rs.cast_creature(rs_fc, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Fungal Colossus at "
        "full {6}{G} cost with a {6}{G}-primed pool (0 lands "
        "controlled — PerDifferentlyNamedLand condition False; "
        "no reduction applies)"
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty (the {6}{G} was paid exactly — no
    # residual mana, no silent over-spend).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (cost "
        f"{{6}}{{G}} paid exactly); got "
        f"{py.players[0].mana_pool}"
    )
    # Hand emptied of the cast instance.
    assert all(o.id != py_fc.id for o in py.players[0].hand), (
        "Python: hand-resident Fungal must leave hand post-cast"
    )
    # Stack carries Fungal.
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_fc.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast; got {rs_pool}"
    )
    # Stack carries Fungal. Successful cast with exactly the
    # {6}{G}-primed pool proves the reduction did NOT apply
    # (auto_tap_pay_for_cost would have short-spent if Rust
    # returned a reduced cost on a 0-lands state — and the pool
    # would carry residual mana).
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Fungal Colossus full-cost scenario (cast with 0 lands; "
        f"PerDifferentlyNamedLand condition False) must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — scenario (b):
# 4 distinctly-named lands → reduced ``{2}{G}`` both seats
# (multiplier=4; the set-semantic distinct path — the load-bearing
# variable-multiplier case). PROBED tier flip (one of three scenarios
# in this Cycle-3 closure marker — ``covered_by_construction`` →
# PROBED, multiplier=4).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_fungal_colossus_reduced_cost_four_distinct_lands_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Fungal Colossus
    reduced-cost scenario (cast with FOUR distinctly-named lands
    controlled). PROBED tier flip evidence (Cycle 3 closure marker
    — ``covered_by_construction`` → PROBED, scenario (b) —
    multiplier=4). THIS is the LOAD-BEARING probe: the variable-X
    ``{1}``-per-distinct-land reduction must apply byte-equal on
    both engines after the HashSet<&str> over land-printing names
    collects 4 distinct keys, multiplier=4, and the
    ``amount * multiplier == 1 * 4 == 4`` generic-drop arithmetic
    on the spell-local variable-multiplier path.**

    Pre-cast state on both engines: ONE Fungal in p0's hand to
    cast, FOUR distinctly-named EoE-land permanents pre-seated on
    p0's battlefield (Breeding Pool / Godless Shrine / Command
    Bridge / Adagia, Windswept Bastion — pulled from the live
    ``OracleParserCardSource`` on Python; injected as bare
    ``card_types=["Land"]`` synthetics carrying the SAME four
    names on Rust since the ``unique_land_names_count`` walk keys
    ONLY on ``printing.name``). p0's mana pool primed with
    ``{2}{G}`` on both engines — the EXACT reduced cost: the {1}
    amount times multiplier-of-4 subtracts {4} of generic from the
    {6}{G} base, leaving generic=2 + G colored pip.

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, fungal_id)``
        drives the full Python cast pipeline: applies cost
        reductions (``apply_cost_reductions`` walks the spell-
        local ``cost_reductions``, finds the
        ``PerDifferentlyNamedLand`` rider, calls
        ``condition.matches(state, 0)`` — walks ``state.battle
        field`` for ``o.controller_id == 0 and o.printing.
        is_land``, the names ``{"Breeding Pool", "Godless Shrine",
        "Command Bridge", "Adagia, Windswept Bastion"}`` collect
        in a set of size 4, ``count == 4 >= 1`` → True — reads
        ``condition.multiplier(state, 0)`` = 4 (the variable-X
        path), applies ``ext.amount * condition.multiplier`` ({1}
        * 4 = 4 generic dropped), the ``ManaCost.reduced(4)``
        arithmetic at ``cards/base.py:298-305`` saturating-subs 4
        generic → ``ManaCost(generic=2, colored=(('G', 1),))``),
        pays via ``auto_tap_for_cost`` (drains 2C + 1G exactly),
        pushes the StackItem, increments
        ``spells_cast_this_turn``, fires IS_CAST.
      * **Rust.** ``cast_creature(fungal_id, 0)`` drives the full
        Rust cast pipeline. The ``apply_cost_reductions_rust``
        helper at ``state_ops_legal.rs:764`` short-circuits the
        empty externals scan, walks the spell-local
        ``cost_reductions``, matches the
        ``Condition::PerDifferentlyNamedLand`` arm at
        ``state_ops_legal.rs:870-893``, calls
        ``unique_land_names_count(state, 0)`` — walks
        ``state.players[0].battlefield`` with a HashSet<&str>
        over ``printing.name`` filtered by ``card_types``
        contains-"Land", the 4 distinct names collect, returns 4
        — ``(count >= 1, count) == (true, 4)``, the multiplier
        IS the count (the variable-X path) — composes through
        ``cost.generic.saturating_sub(amt_clamped)`` with
        ``amt = 1 * 4 = 4`` (the mirror of Python
        ``ManaCost.reduced`` at ``cards/base.py:291-305``) →
        ManaCost(generic=2, G=1). Pays via
        ``auto_tap_pay_for_cost`` (drains 2C + 1G), rehomes to
        the stack-source store, dispatches Event::Cast,
        increments ``spells_cast_this_turn``, pushes the
        StackItem.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack.

    Critical bytes the probe pins:
      * Pool empty on both post-cast (the reduced {2}{G} was paid
        exactly — Rust did NOT silently pay through 6 colorless
        the way the pre-Phase-3 false-emission would have; both
        engines applied the SAME {4} = {1} * 4 amount-times-
        multiplier reduction on the spell-local variable-
        multiplier path).
      * Fungal off hand, on stack on both.
      * The 4 seated lands still on p0's battlefield (the
        cost-payment scan is read-only — no land-tap noise since
        the pool was pre-primed).

    **This is the case that diverges pre-Phase-3** (per design
    doc §3 / §7.3 admit table). The Phase-3 Cycle-1 substrate
    landed the byte-equal arithmetic on both sides via the
    ``apply_cost_reductions_rust`` spell-local match extension +
    ``unique_land_names_count`` helper; the Phase-3 Cycle-2 FLIP
    widened the admit predicate to admit Fungal. This probe is
    the live-printing, actual-cast byte-equal proof on the
    variable-multiplier spell-local condition variant — exactly
    the "round-46 real-EoE-signal discipline" floor for the
    ``PerDifferentlyNamedLand`` variable-X carrier.
    """
    from mtg_bot.actions import _cast_spell
    from mtg_bot.game import ManaCoin, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    real = _PRINTINGS.get("Fungal Colossus")
    if real is None:
        pytest.skip("Fungal Colossus absent from active CardSource")
    # Pre-check that the chosen scenario-(b) lands exist in the
    # active CardSource — they're all real EoE-pool lands.
    for land_name in _FOUR_DISTINCT_LAND_NAMES:
        if _PRINTINGS.get(land_name) is None:
            pytest.skip(
                f"Scenario-(b) land {land_name!r} absent from "
                f"active CardSource"
            )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Scripted picker (design doc §7.3): seat 4 distinctly-named
    # real-EoE lands on p0's bf, THEN Fungal in p0's hand on BOTH
    # engines in lockstep. The injection order (4 lands first, then
    # the hand Fungal) keeps the per-zone object_id allocation in
    # lockstep across engines so the cross-engine field-view
    # comparison agrees on id slots.
    py_lands: list = []
    for land_name in _FOUR_DISTINCT_LAND_NAMES:
        lp = _PRINTINGS[land_name]
        obj = py.new_object(lp, owner_id=0, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        obj.etb_timestamp = py.next_timestamp
        py.next_timestamp += 1
        py.battlefield.append(obj)
        py_lands.append(obj)

    py_fc = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py_fc.summoning_sick = False
    py.players[0].hand.append(py_fc)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="G"),
    ])

    # ---- Rust: register 4 same-named-as-Python land synthetics in
    # p0's battlefield (zone 2) FIRST, then the hand Fungal (zone 0).
    # The ``unique_land_names_count`` walk keys ONLY on
    # ``printing.name``; a bare ``card_types=["Land"]`` shape carrying
    # the SAME name as the Python side is sufficient to drive
    # byte-equal multiplier evaluation.
    rs_land_ids: list = []
    for land_name in _FOUR_DISTINCT_LAND_NAMES:
        rs_l = rs.register_and_inject_object(
            {"name": land_name, "card_types": ["Land"]},
            0, 2,  # controller=0, zone=2 (BATTLEFIELD)
        )
        rs_land_ids.append(rs_l)
    rs_fc = rs.register_and_inject_object(_FUNGAL_RUST_DICT, 0, 0)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "G", 1)

    # Pre-cast sanity: 4 lands on p0's bf on both engines; stack
    # empty on both.
    assert len(py.battlefield) == 4
    assert all(o.controller_id == 0 for o in py.battlefield)
    assert sum(
        1 for o in py.battlefield
        if "Land" in (o.printing.card_types or ())
    ) == 4
    # Distinct-name set is size 4 (the multiplier-axis sanity).
    assert len({o.printing.name for o in py.battlefield}) == 4
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # Pre-cast cross-engine field-view sanity — the scripted-picker
    # setup is byte-equal on BOTH engines before any cast fires.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-cast 4-distinct-lands setup must be byte-equal "
        f"across engines (4 distinctly-named lands + hand Fungal + "
        f"{{2}}{{G}}-primed pool); got pre_diffs={pre_diffs}"
    )

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_fc.id)
    ok = rs.cast_creature(rs_fc, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Fungal Colossus at "
        "REDUCED {2}{G} cost (with 4 distinctly-named lands "
        "controlled) with a {2}{G}-primed pool — the {1}-per-"
        "distinct-land * 4 = {4} reduction MUST apply, and the "
        "apply_cost_reductions_rust helper MUST walk p0's bf with "
        "unique_land_names_count, find 4 distinct land names, "
        "evaluate count >= 1 -> True with multiplier=4, and return "
        "ManaCost(generic=2, G=1). If this fails as 'insufficient "
        "mana' it means the reduction did NOT fire — either the "
        "Phase-3 Cycle-1 substrate did not apply the spell-local "
        "cost reduction on the live printing, or the unique-name "
        "set scan missed the seeded lands, or the variable-X "
        "multiplier arithmetic mis-counted."
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty: only {2}{G} was paid (2 colorless +
    # 1 green). If the reduction did NOT apply on Python somehow,
    # the cast would have failed at auto_tap_for_cost (insufficient
    # mana — we primed only 3 coins, not 7).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (reduced cost "
        f"{{2}}{{G}} paid exactly); got "
        f"{py.players[0].mana_pool}. A non-empty pool here means "
        f"the reduction over-applied (paid less than expected); a "
        f"failed-cast path would surface at auto_tap_for_cost."
    )
    # Hand emptied of the cast instance.
    assert all(o.id != py_fc.id for o in py.players[0].hand)
    # 4 seated lands still present (cost-payment scan is read-only —
    # the pool was pre-primed so no land taps fired).
    assert len(py.battlefield) == 4
    assert sum(
        1 for o in py.battlefield
        if "Land" in (o.printing.card_types or ())
    ) == 4
    # Stack carries Fungal.
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_fc.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast (reduced cost paid "
        f"exactly); got {rs_pool}. A non-empty pool means the "
        f"reduction over-applied; a successful cast with a "
        f"non-empty pool would mean the Rust helper returned a "
        f"smaller cost than Python's apply_cost_reductions."
    )
    # Stack carries Fungal. The successful cast with the {2}{G}-only
    # primed pool is the load-bearing inline check: the Rust
    # spell-local helper MUST have walked p0's bf with
    # unique_land_names_count, found 4 distinct land names →
    # multiplier=4, evaluated count >= 1 → True, and returned the
    # reduced {2}{G} cost via the saturating_sub of (1 * 4) = 4
    # generic; otherwise auto_tap_pay_for_cost would have short-
    # spent at the {6}{G} base.
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Fungal Colossus reduced-cost scenario (cast with 4 "
        f"distinctly-named lands controlled — the {{1}}-per-"
        f"distinct-land * multiplier=4 = {{4}} spell-local "
        f"reduction applies via PerDifferentlyNamedLand) must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}. This is the load-bearing byte-equal that "
        f"the Phase-3 Cycle-1 substrate FLIP rides on for the "
        f"variable-multiplier spell-local carrier — a divergence "
        f"here is an honest-stop signal."
    )


# ---------------------------------------------------------------------------
# (6) GENUINE real-EoE cross-engine byte-equal probe — scenario (c):
# 4 same-named lands → reduced ``{5}{G}`` both seats (multiplier=1;
# the set-semantic edge case where 4 copies of the same land collapse
# to a single distinct name). PROBED tier flip (one of three scenarios
# in this Cycle-3 closure marker — ``covered_by_construction`` →
# PROBED, multiplier=1).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_fungal_colossus_reduced_cost_four_same_lands_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Fungal Colossus
    reduced-cost scenario (cast with FOUR same-named lands
    controlled). PROBED tier flip evidence (Cycle 3 closure marker
    — ``covered_by_construction`` → PROBED, scenario (c) —
    multiplier=1; the set-semantic edge case).**

    **THE SET-SEMANTIC TEETH.** A naive implementation that counted
    raw caster's lands (instead of distinctly-named lands) would
    multiply by 4 and return ``{2}{G}`` (the same as scenario (b));
    this scenario proves both engines key the multiplier on the
    DISTINCT-NAME set, not the raw count — the
    ``unique_land_names_count`` HashSet<&str> collapses 4 copies of
    Breeding Pool to a single ``"Breeding Pool"`` key,
    multiplier=1, ``amount * multiplier == 1 * 1 == 1`` generic
    dropped, returns ``ManaCost(generic=5, G=1)``.

    Pre-cast state on both engines: ONE Fungal in p0's hand to
    cast, FOUR copies of the SAME EoE land (Breeding Pool ×4) pre-
    seated on p0's battlefield. Fungal's
    ``PerDifferentlyNamedLand`` walks p0's bf — 4 land permanents,
    but the HashSet<&str> over ``printing.name`` collapses all 4
    to a single ``"Breeding Pool"`` key, ``count == 1 >= 1`` is
    True, ``multiplier == 1``. p0's mana pool primed with
    ``{5}{G}`` on both engines — the EXACT reduced cost: the {1}
    amount times multiplier-of-1 subtracts {1} of generic from the
    {6}{G} base, leaving generic=5 + G colored pip.

    Cast on both engines: same shape as scenario (b) but with
    multiplier=1 instead of 4. The Python side reads
    ``condition.multiplier(state, 0)`` = 1 (the set size collapses
    to 1). The Rust side's ``unique_land_names_count`` walks
    p0's bf, the HashSet<&str> over ``printing.name`` inserts
    "Breeding Pool" four times but the set retains size 1; returns
    1 — ``(count >= 1, count) == (true, 1)``, multiplier=1 —
    composes through ``cost.generic.saturating_sub(amt_clamped)``
    with ``amt = 1 * 1 = 1`` → ManaCost(generic=5, G=1).

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack.

    Critical bytes the probe pins:
      * Pool empty on both post-cast (the reduced {5}{G} was paid
        exactly — the {1} reduction was actually applied as
        ``amount * multiplier`` with multiplier=1, NOT the
        raw-count multiplier=4 that a naive bf-walking
        implementation would yield).
      * Fungal off hand, on stack on both.
      * The 4 same-named lands still on p0's battlefield (cost-
        payment scan is read-only).

    **The set-semantic teeth is the load-bearing distinction from
    scenario (b).** A subtle Rust-side bug that miscounted the
    HashSet — e.g. keying on ``printing_id`` instead of
    ``printing.name`` (each Breeding Pool synthetic gets a fresh
    printing_id, but they all share the printing.name "Breeding
    Pool") — would over-apply the reduction by a factor of 4 here,
    leaving the pool with residual 3 colorless after the cast (and
    a divergence flag). This scenario forces both engines into
    that exact failure mode if the set-semantic distinction is
    broken on either side.
    """
    from mtg_bot.actions import _cast_spell
    from mtg_bot.game import ManaCoin, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    real = _PRINTINGS.get("Fungal Colossus")
    if real is None:
        pytest.skip("Fungal Colossus absent from active CardSource")
    # Scenario (c) uses Breeding Pool — pulled from the live
    # ``OracleParserCardSource`` on Python.
    same_land_name = "Breeding Pool"
    if _PRINTINGS.get(same_land_name) is None:
        pytest.skip(
            f"Scenario-(c) land {same_land_name!r} absent from "
            f"active CardSource"
        )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Scripted picker: seat 4 copies of the SAME real-EoE land
    # on p0's bf, then Fungal in p0's hand on BOTH engines.
    same_lp = _PRINTINGS[same_land_name]
    py_lands: list = []
    for _ in range(4):
        obj = py.new_object(same_lp, owner_id=0, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        obj.etb_timestamp = py.next_timestamp
        py.next_timestamp += 1
        py.battlefield.append(obj)
        py_lands.append(obj)

    py_fc = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py_fc.summoning_sick = False
    py.players[0].hand.append(py_fc)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="G"),
    ])

    # ---- Rust: register 4 same-named-as-Python land synthetics
    # (each gets its own printing_id but they all share the SAME
    # printing.name "Breeding Pool") on p0's battlefield, then the
    # hand Fungal.
    rs_land_ids: list = []
    for _ in range(4):
        rs_l = rs.register_and_inject_object(
            {"name": same_land_name, "card_types": ["Land"]},
            0, 2,
        )
        rs_land_ids.append(rs_l)
    rs_fc = rs.register_and_inject_object(_FUNGAL_RUST_DICT, 0, 0)
    for _ in range(5):
        rs.add_mana(0, "C", 1)
    rs.add_mana(0, "G", 1)

    # Pre-cast sanity: 4 lands on p0's bf on both engines, BUT the
    # distinct-name set is size 1 (the set-semantic axis the
    # multiplier reads).
    assert len(py.battlefield) == 4
    assert all(o.controller_id == 0 for o in py.battlefield)
    assert sum(
        1 for o in py.battlefield
        if "Land" in (o.printing.card_types or ())
    ) == 4
    # Distinct-name set is size 1 (the load-bearing axis).
    assert len({o.printing.name for o in py.battlefield}) == 1
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # Pre-cast cross-engine field-view sanity.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-cast 4-same-named-lands setup must be byte-equal "
        f"across engines (4 copies of {same_land_name!r} + hand "
        f"Fungal + {{5}}{{G}}-primed pool); got "
        f"pre_diffs={pre_diffs}"
    )

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_fc.id)
    ok = rs.cast_creature(rs_fc, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Fungal Colossus at "
        "REDUCED {5}{G} cost (with 4 SAME-named lands controlled "
        "— set collapses to multiplier=1) with a {5}{G}-primed "
        "pool. If this fails it means the unique-name set walk "
        "mis-counted (e.g. keyed on printing_id instead of "
        "printing.name, yielding multiplier=4 and over-reducing "
        "to {2}{G})."
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty: only {5}{G} was paid (5 colorless +
    # 1 green). The set-semantic distinction means multiplier=1,
    # NOT 4 — so the cost is {5}{G}, NOT {2}{G}.
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (reduced cost "
        f"{{5}}{{G}} paid exactly — the set-semantic distinction "
        f"means multiplier=1 from 4 same-named lands, NOT "
        f"multiplier=4); got {py.players[0].mana_pool}"
    )
    # Hand emptied of the cast instance.
    assert all(o.id != py_fc.id for o in py.players[0].hand)
    # 4 seated lands still present (cost-payment scan is read-only).
    assert len(py.battlefield) == 4
    assert sum(
        1 for o in py.battlefield
        if "Land" in (o.printing.card_types or ())
    ) == 4
    # Stack carries Fungal.
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_fc.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast (reduced cost "
        f"{{5}}{{G}} paid exactly — the set-semantic distinction "
        f"means multiplier=1, NOT 4); got {rs_pool}. A non-empty "
        f"pool means the set walk mis-counted on the Rust side."
    )
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Fungal Colossus reduced-cost scenario (cast with 4 "
        f"same-named lands controlled — the set-semantic "
        f"multiplier=1 case) must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}. This is the "
        f"set-semantic teeth for the variable-X multiplier path — "
        f"divergence here means one engine counts raw lands "
        f"instead of distinct names."
    )
