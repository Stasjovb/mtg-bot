"""Sami, Wildcat Captain Cycle 4 — per-card real-EoE cross-engine
byte-equality probe (``covered_by_construction`` → PROBED tier flip;
**THE FINAL probe of cost-reduction Phase 2**).

Sami, Wildcat Captain is a ``{4}{R}{W}`` Creature — Human Artificer
Rogue (4/4 with ``vigilance`` and ``double strike``, EoE — sourced
from ``data/edge_of_eternities.json``) with a single Phase-2 EXTERNAL
cost-reduction rider:

    "This spell costs {1} less to cast for each artifact you control."

Parsed into one
``ExternalCostReduction(amount=1, condition=PerControlled(filter=
IsArtifact()))`` under ``printing.external_cost_reductions`` (Phase-2
sub-shape C — the affinity-style variable-multiplier path). No
spell-local ``cost_reductions``, no spell effect, no triggered or
activated abilities, no warp/impending — the cleanest Sub-shape-C
Phase-2 carrier modulo the ``vigilance`` + ``double strike`` static
keywords (both in :data:`mtg_bot.parity.trajectory._SAFE_KEYWORDS`,
admitted via the bridge predicate's keyword allowance, sibling to the
Lashwhip Phase-1 C4 ``reach`` shape — per ``docs/COST_REDUCTION_
SUBSTRATE_PHASE_2_DESIGN.md`` §3).

**Multi-cycle DECLINED → ADMITTED → PROBED transition (this lane is
the closure marker for Phase 2 — the LAST sub-shape of the campaign;
sub-shape D ``PerDifferentlyNamedLand`` on Fungal Colossus is Phase 3
territory).**

  * **Phase 1 Cycle 1 (substrate, commit ``3683e62e``).** Rust
    ``CostReduction`` + ``Condition`` enum + ``Printing.cost_
    reductions`` (Phase-1 spell-local field) + Phase-1 evaluator hook.
    Sami stayed DECLINED — Sami's rider lives on the EXTERNAL axis
    AND uses a variable-multiplier condition, neither of which the
    Phase-1 substrate carried.
  * **Phase 1 Cycle 2 (commit ``8593b0fb``, 2026-05-24).** The
    bridge admit predicate
    ``_printing_is_bridge_pure_cost_reduction_creature`` landed but
    its §2 teeth EXPLICITLY rejected any printing carrying
    ``external_cost_reductions``; Sami stayed DECLINED with that
    reject hard-coded.
  * **Phase 2 Cycle 1 (substrate, commit ``5fa32697``, 2026-05-25).**
    Rust ``ExternalCostReduction`` + ``ExternalCondition`` enum
    subset (``NthSpellThisTurn`` + ``PerControlled``) + the new
    ``TypeFilter::Artifact`` variant + ``CardPrinting.external_cost_
    reductions`` field + ``parse_printing`` tag-dispatch + the
    ``apply_external_cost_reductions_rust`` helper (externals-first
    ordering — mirrors Python ``actions.apply_cost_reductions`` at
    ``actions.py:428-438``). Sami's variable-multiplier path landed
    here: ``ExternalCondition::PerControlled.multiplier`` IS the
    counted-permanents total (``state_ops_legal.rs:924-957``).
    Sami stayed DECLINED at the admit gate (the C1 admit predicate
    still rejected ``external_cost_reductions``).
  * **Phase 2 Cycle 2 (THE FLIP, commit ``c370cee4``, 2026-05-25).**
    The CardDef ``external_cost_reductions`` field + bridge round-
    trip arms (``_spec_card_to_printing_dict`` Phase-2 emit +
    ``_card_def_to_python_printing`` Phase-2 reverse arm) + the
    widened admit predicate (Option A — the OLD
    ``external_cost_reductions`` reject swapped for an admit-loop
    against ``_external_cost_reduction_rule_is_phase2``). Uthros +
    Sami simultaneously flipped DECLINED → ADMITTED (the 2-card
    +15,575 17lands-deck single-cycle FLIP; the C2 substrate pin
    set pins admit set EXACTLY ``{"Gigastorm Titan", "Lashwhip
    Predator", "Sami, Wildcat Captain", "Uthros Psionicist"}``).
  * **Phase 2 Cycle 3 (commit ``809d546c``, 2026-05-25).** Uthros
    Psionicist's per-card real-EoE byte-equal probe landed —
    ``covered_by_construction`` → PROBED on the
    ``NthSpellThisTurn`` external carrier (sub-shape B).
  * **Phase 2 Cycle 4 (THIS LANE; the FINAL probe of Phase 2).**
    Per-card real-EoE cross-engine byte-equality probe driving BOTH
    lifecycles (full-cost cast with 0 artifacts controlled +
    reduced-cost cast with 2 artifacts pre-seated on caster's bf,
    multiplier=2 so the {1}-per-artifact reduction drops {2} of
    generic — the load-bearing affinity-style variable-multiplier
    case) flips ``covered_by_construction`` → PROBED in the
    pool-parity metric. Sami is the SECOND and LAST Phase-2
    cost-reduction carrier; with this commit, BLOCKED drops
    57 → 56 and **Phase 2 closure is complete** (~15,575 17lands
    decks unblocked at the admit gate over Cycles 2 + 3 + 4;
    ~808 decks attributable to Sami specifically per the design
    doc's per-card breakdown).

**Lifecycle coverage.** Both Phase-2 external-cost-reduction paths
are exercised through ``PerControlled(IsArtifact())`` — the FIRST
non-trivial-multiplier ExternalCondition variant; the multiplier IS
the count of caster-controlled artifacts (affinity-style scaling per
``effects/conditions.py:418-434`` Python /
``state_ops_legal.rs:924-957`` Rust):

  * **Full-cost lifecycle (lifecycle A).** Pre-cast state: ONE
    Sami-shape carrier on the caster's battlefield (the rider
    source — externals only fire when the carrier is on-bf; the
    helper walks the caster's bf at ``state_ops_legal.rs:903``),
    ZERO artifacts on either battlefield. Sami herself is a
    Creature (not an Artifact — her ``card_types`` is exactly
    ``("Creature",)``, subtypes are ``"Human","Artificer","Rogue"``
    — Artificer is a CR 205.3 creature subtype, not a card type),
    so the carrier does NOT self-count. Sami pays her base
    ``{4}{R}{W}`` — the ``PerControlled(IsArtifact())`` condition
    is False (0 caster artifacts < 1, ``count >= 1`` is False),
    the reduction does NOT apply. Pool primed with 4 colorless +
    1 red + 1 white on both engines so ``auto_tap_pay_for_cost``
    (Rust) / ``auto_tap_for_cost`` (Python) drain the pool cleanly
    without needing lands. Asserts full ``compare_fields == []``
    post-cast: pool empty on both, Sami (hand instance) from hand
    now on the stack on both, the bf-resident Sami carrier
    untouched.
  * **Reduced-cost lifecycle (lifecycle B).** Pre-cast state: ONE
    Sami-shape carrier on the caster's battlefield (the rider
    source), TWO vanilla Artifact-shape permanents pre-seated on
    p0's battlefield via the scripted picker —
    ``register_and_inject_object`` on Rust (controller=0,
    zone=ZONE_BATTLEFIELD) + ``new_object`` +
    ``state.battlefield.append`` on Python (owner_id=0,
    zone=Zone.BATTLEFIELD). Sami's
    ``PerControlled(IsArtifact()).matches`` evaluates against
    ``count == 2 >= 1`` → True; ``multiplier == 2`` (the
    affinity-style scaling — the multiplier IS the count, NOT a
    constant 1 like ``NthSpellThisTurn``). The reduction applies
    and ``apply_external_cost_reductions_rust`` returns
    ``ManaCost(generic=2, R=1, W=1)`` (the {1} amount times the
    multiplier-of-2 = {2} of generic dropped from the {4}{R}{W}
    base, saturating to generic=2). Pool primed with 2 colorless
    + 1 red + 1 white on both engines (the EXACT reduced cost).
    Asserts full ``compare_fields == []`` post-cast: pool empty on
    both, NO residual generic (the {2} reduction was actually
    applied as ``amount * multiplier``, NOT silently paid through
    4 colorless), Sami (hand instance) on the stack on both, the
    bf carrier untouched, the 2 artifact carriers still on p0's
    battlefield unchanged.

**This is the LOAD-BEARING evidence for the Phase 2 Cycle 2 FLIP's
SECOND carrier — and the variable-multiplier code path proof.** The
C2 admit predicate trusted ``apply_external_cost_reductions_rust``
to mirror Python's ``_apply_external_cost_reductions`` byte-equal
for BOTH Phase-2 external-condition shapes; this probe is the
per-card proof that the round-46 real-EoE-signal discipline ('do NOT
trust synthetic CardDefs; drive the live ``OracleParserCardSource``
printing') holds at the cast-and-pay level for the
``PerControlled(IsArtifact())`` variable-multiplier variant, not just
at the substrate fixture level. The Cycle-3 sibling probe (Uthros
Psionicist ``809d546c``) pinned the ``NthSpellThisTurn``
implicit-multiplier-1 carrier; this probe pins the affinity-style
variable-multiplier carrier — together they exhaust the Phase-2
ExternalCondition variant surface byte-equal AND validate that the
``amount * multiplier`` arithmetic at
``state_ops_legal.rs:967-969`` (Rust: ``ext.amount * multiplier``
clamped at ``u8::MAX`` before ``saturating_sub``) mirrors Python's
``ext.amount * condition.multiplier`` byte-equal on a real-EoE
carrier.

The post-resolve permanent-on-bf check sits outside this probe's
scope (parallel to the Cycle-3 sibling) — the cast-and-pay path is
the part the Cycle 2 substrate touched; the resolve path was
unchanged. This module concentrates on the cost-payment
byte-equality: pool debit, generic/colored split, the externals
battlefield scan that powers the Sami reduction, and the
amount-times-multiplier arithmetic on the variable-multiplier path.
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
# (1) Parser SoT — Sami, Wildcat Captain is parser-claimed and emits
# the expected Phase-2 external cost-reduction shape (the Cycle-1
# substrate pin, duplicated here so this module is self-contained for
# the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_sami_wildcat_captain_parser_claims_card():
    assert "Sami, Wildcat Captain" in _PRINTINGS, (
        "Sami, Wildcat Captain must be parser-claimed by the active "
        "CardSource (EoE set)"
    )


def test_sami_wildcat_captain_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T,
    ``vigilance`` + ``double strike`` static keywords, single
    Phase-2 EXTERNAL cost-reduction rider on the
    ``external_cost_reductions`` axis; no other riders, no
    spell-local ``cost_reductions``)."""
    from mtg_bot.cards.base import ExternalCostReduction
    from mtg_bot.effects.conditions import PerControlled
    from mtg_bot.effects.object_predicates import IsArtifact

    p = _PRINTINGS["Sami, Wildcat Captain"]
    assert p.mana_cost_str == "{4}{R}{W}"
    assert "Creature" in p.card_types
    assert "Artifact" not in p.card_types, (
        "Sami must NOT be Artifact-typed — Artificer is a CREATURE "
        "subtype (CR 205.3), not a card type. The PerControlled"
        "(IsArtifact()) carrier must not self-count."
    )
    assert "Human" in p.subtypes
    assert "Artificer" in p.subtypes
    assert "Rogue" in p.subtypes
    assert p.power == 4
    assert p.toughness == 4
    assert "vigilance" in p.keywords
    assert "double strike" in p.keywords
    # Phase-2 external cost-reduction rider — the load-bearing shape.
    assert p.cost_reductions == ()
    assert len(p.external_cost_reductions) == 1
    (ext_rule,) = p.external_cost_reductions
    assert isinstance(ext_rule, ExternalCostReduction)
    assert ext_rule.amount == 1
    assert isinstance(ext_rule.condition, PerControlled)
    assert isinstance(ext_rule.condition.filter, IsArtifact)
    # No spell_effect / abilities / warp / impending — the cleanest
    # Sub-shape-C carrier per the design doc §3 (modulo the static
    # keywords which are admitted via _SAFE_KEYWORDS).
    assert not p.triggered_abilities
    assert not p.activated_abilities
    assert not p.static_abilities
    assert p.spell_effect is None
    assert p.warp_cost is None


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — Python printing → CardDef → Rust dict →
# Python printing round-trips byte-equal on the
# external_cost_reductions axis. Duplicated from the Phase-2 Cycle-2
# substrate pin so the per-card module is self-contained for the
# PROBED-tier evidence.
# ---------------------------------------------------------------------------


def test_sami_wildcat_captain_bridge_round_trip_byte_equal():
    """The Phase-2 Cycle-2 bridge: Python printing →
    ``_printing_to_card_def`` → ``CardDef.external_cost_reductions``
    triple → ``_spec_card_to_printing_dict`` Rust dict →
    ``Registry.register_printing`` → ``_card_def_to_python_printing``
    Python printing whose ``external_cost_reductions`` is byte-equal
    to the live-parsed input."""
    import mtg_bot_engine
    from mtg_bot.cards.base import ExternalCostReduction
    from mtg_bot.effects.conditions import PerControlled
    from mtg_bot.effects.object_predicates import IsArtifact
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    p_orig = _PRINTINGS["Sami, Wildcat Captain"]
    cd = trajectory._printing_to_card_def(p_orig)
    assert cd.external_cost_reductions == (
        (1, "per_controlled", ("artifact",)),
    )
    # Phase-1 spell-local axis stays empty — Sami carries externals
    # only.
    assert cd.cost_reductions == ()
    d = _spec_card_to_printing_dict(cd)
    assert d.get("external_cost_reductions") == [
        {
            "amount": 1,
            "condition_kind": "per_controlled",
            "condition_args": ("artifact",),
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
    assert ext_rt.amount == 1
    assert isinstance(ext_rt.condition, PerControlled)
    assert isinstance(ext_rt.condition.filter, IsArtifact)


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the Phase-2 external cost-reduction
# condition tag ``per_controlled`` with predicate token ``artifact``
# parses on a Sami-shape printing via ``register_and_inject_object``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_sami_wildcat_captain_synthetic_dict():
    """Lockstep pin: Rust's parse arm accepts the
    ``{"amount": 1, "condition_kind": "per_controlled",
    "condition_args": ("artifact",)}`` payload on a Sami-shape
    synthetic carrier (the dict shape ``_spec_card_to_printing_dict``
    emits for the ``external_cost_reductions`` axis of Sub-shape C —
    the variable-multiplier ``PerControlled(IsArtifact())``
    variant)."""
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sid = rs.register_and_inject_object(
        {
            "name": "Sami, Wildcat Captain (synthetic carrier)",
            "card_types": ["Creature"],
            "subtypes": ["Human", "Artificer", "Rogue"],
            "mana_cost": {"generic": 4, "R": 1, "W": 1},
            "power": 4,
            "toughness": 4,
            "keywords": ["double_strike", "vigilance"],
            "external_cost_reductions": [
                {
                    "amount": 1,
                    "condition_kind": "per_controlled",
                    "condition_args": ("artifact",),
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
# Lifecycle A: cast Sami with a Sami-shape carrier on caster's bf but
# ZERO controlled artifacts. The PerControlled(IsArtifact()) condition
# evaluates `count == 0 >= 1` → False, so the reduction does NOT apply
# and both engines pay the base {4}{R}{W}.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_sami_wildcat_captain_full_cost_zero_artifacts_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Sami, Wildcat Captain
    full-cost lifecycle (cast with ONE Sami-shape carrier on the
    caster's battlefield but ZERO controlled artifacts). PROBED tier
    flip evidence (Cycle 4 closure marker — ``covered_by_construction``
    → PROBED, lifecycle A).**

    Pre-cast state on both engines: ONE Sami-shape carrier already
    on p0's battlefield (so the externals scan finds the rider but
    its ``PerControlled(IsArtifact())`` condition evaluates False —
    ``count == 0 < 1``), a second Sami in p0's hand to actually
    cast, ZERO artifacts on either battlefield, p0's mana pool
    primed with {4}{R}{W} (4 colorless + 1 red + 1 white, exactly
    the base ``mana_cost`` Sami needs when her reduction does not
    apply). Note: Sami herself is a Creature (NOT an Artifact —
    ``card_types`` is exactly ``("Creature",)``), so the carrier
    does NOT self-count toward the artifact total. No spells
    previously cast.

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, sami_id)``
        drives the full Python cast pipeline (selects empty
        targets, applies cost reductions via
        ``apply_cost_reductions`` at ``actions.py``: walks the
        caster's battlefield via ``_apply_external_cost_reductions``,
        finds the Sami-shape carrier's
        ``external_cost_reductions``, evaluates
        ``PerControlled(IsArtifact()).matches`` against the caster's
        bf — 0 artifact-type permanents found, ``count >= 1`` →
        False — no reduction applies; then walks the spell-local
        ``cost_reductions`` — empty for Sami — no-op. Pays via
        ``auto_tap_for_cost``, pushes the ``StackItem``, increments
        ``spells_cast_this_turn``, fires IS_CAST).
      * **Rust.** ``cast_creature(sami_id, 0)`` drives the full
        Rust cast pipeline. The
        ``apply_cost_reductions_rust(state, idx, printing, base)``
        helper at ``state_ops_legal.rs:764`` calls
        ``apply_external_cost_reductions_rust`` FIRST (the
        externals-first ordering pinned in Phase 2 Cycle 1; mirrors
        Python ``actions.py:428-438``); that helper walks the
        caster's bf at ``state_ops_legal.rs:903``, finds the
        Sami-shape carrier's ``external_cost_reductions``, evaluates
        ``ExternalCondition::PerControlled { type_filter:
        TypeFilter::Artifact }`` — scans caster's bf at
        ``state_ops_legal.rs:933-955`` for permanents whose
        ``card_types`` contains ``"Artifact"`` — 0 here — so
        ``count >= 1`` is False, no reduction applies; the empty
        spell-local ``cost_reductions`` then short-circuits to the
        base cost. Pays via ``auto_tap_pay_for_cost``, rehomes to
        the stack-source store, dispatches Event::Cast, increments
        ``spells_cast_this_turn``, pushes the StackItem.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack. Mana pool MUST
    be empty on both (the full {4}{R}{W} was paid — no silent
    over-spend), Sami (hand instance) MUST be off the hand and on
    the stack on both, the bf-resident Sami carrier MUST stay on
    the battlefield untouched.

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

    real = _PRINTINGS.get("Sami, Wildcat Captain")
    if real is None:
        pytest.skip("Sami, Wildcat Captain absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat a Sami-shape carrier on p0's battlefield
    # (the cost-reduction source — externals only fire when the
    # carrier is on-bf), then seat a second Sami in p0's hand to
    # cast. Default Python ``new_object`` sets
    # ``summoning_sick=True``; align with Rust's
    # ``register_and_inject_object`` default of False on both the
    # bf carrier and the hand instance so the cross-engine field
    # view agrees byte-equal at the per-zone object-sig granularity.
    py_bf_sami = py.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bf_sami.summoning_sick = False
    py.battlefield.append(py_bf_sami)
    py_hand_sami = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py_hand_sami.summoning_sick = False
    py.players[0].hand.append(py_hand_sami)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="R"),
        ManaCoin(color="W"),
    ])
    # Sanity: no artifacts on either battlefield (the
    # PerControlled(IsArtifact()) condition is False — count == 0 < 1
    # — the {1}-per-artifact reduction must NOT apply, both engines
    # pay the base {4}{R}{W}).
    assert not any(
        "Artifact" in (o.printing.card_types or ()) for o in py.battlefield
    )

    # ---- Rust: register a Sami-shape carrier in p0's battlefield
    # (zone 2) FIRST, then register the hand instance (zone 0). The
    # bridge round-trip (test 2) already pinned the Python printing
    # → Rust dict shape; reuse the same canonical dict here for both
    # injections. The injection order (bf carrier first, then hand
    # instance) keeps the per-zone object_id allocation in lockstep
    # across engines so the cross-engine field-view comparison
    # agrees on id slots.
    sami_dict = {
        "name": "Sami, Wildcat Captain",
        "card_types": ["Creature"],
        "subtypes": ["Human", "Artificer", "Rogue"],
        "mana_cost": {"generic": 4, "R": 1, "W": 1},
        "power": 4,
        "toughness": 4,
        "keywords": ["double_strike", "vigilance"],
        "external_cost_reductions": [
            {
                "amount": 1,
                "condition_kind": "per_controlled",
                "condition_args": ("artifact",),
            },
        ],
    }
    rs_bf_sami = rs.register_and_inject_object(
        sami_dict, 0, 2,  # controller=0, zone=2 (BATTLEFIELD)
    )
    rs_hand_sami = rs.register_and_inject_object(
        sami_dict, 0, 0,  # controller=0, zone=0 (HAND)
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "R", 1)
    rs.add_mana(0, "W", 1)

    # Pre-cast sanity: nothing on the stack on either engine.
    assert len(py.stack) == 0 and rs.stack_size() == 0
    # The bf carrier is on both engines.
    assert len(py.battlefield) == 1
    assert py.battlefield[0].controller_id == 0

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_hand_sami.id)
    ok = rs.cast_creature(rs_hand_sami, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Sami, Wildcat Captain "
        "at full {4}{R}{W} cost with a {4}{R}{W}-primed pool (0 "
        "artifacts controlled — PerControlled(IsArtifact()) "
        "condition False; no reduction applies)"
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty (the {4}{R}{W} was paid exactly — no
    # residual mana, no silent over-spend).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (cost "
        f"{{4}}{{R}}{{W}} paid exactly); got "
        f"{py.players[0].mana_pool}"
    )
    # Hand emptied of the cast instance (the bf-resident Sami
    # remains on the battlefield unaffected).
    assert all(
        o.id != py_hand_sami.id for o in py.players[0].hand
    ), "Python: hand-resident Sami must leave hand post-cast"
    # bf carrier untouched.
    assert any(
        o.id == py_bf_sami.id for o in py.battlefield
    ), "Python: bf-resident Sami carrier must stay on battlefield"
    # Stack carries Sami.
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_hand_sami.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast; got {rs_pool}"
    )
    # Stack carries Sami. The successful cast with exactly the
    # {4}{R}{W}-primed pool proves the reduction did NOT apply
    # (auto_tap_pay_for_cost would have short-spent if Rust
    # returned a reduced cost on a 0-artifacts-controlled state —
    # and the pool would carry residual mana).
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Sami, Wildcat Captain full-cost lifecycle (cast with a "
        f"bf-resident carrier but 0 controlled artifacts; "
        f"PerControlled(IsArtifact()) condition False) must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — reduced-cost
# lifecycle. PROBED tier flip (one of two lifecycles in this Cycle-4
# closure marker — ``covered_by_construction`` → PROBED, lifecycle B).
# This is THE load-bearing case the C2 bridge admit predicate trusts
# for the variable-multiplier path: both engines apply the {1} *
# multiplier=2 external reduction byte-equal after scanning the
# caster's battlefield for both the Sami-shape carrier AND counting
# IsArtifact matches → 2 → multiplier=2 → 2 generic dropped.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_sami_wildcat_captain_reduced_cost_two_artifacts_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Sami, Wildcat Captain
    reduced-cost lifecycle (cast with the Sami-shape carrier on the
    caster's battlefield AND 2 controlled artifacts pre-seated on
    p0's battlefield). PROBED tier flip evidence (Cycle 4 closure
    marker — ``covered_by_construction`` → PROBED, lifecycle B).
    THIS is the load-bearing probe: the affinity-style
    variable-multiplier {1}-per-artifact reduction must apply
    byte-equal on both engines after scanning the caster's
    battlefield, counting 2 IsArtifact matches, and computing
    ``amount * multiplier == 1 * 2 == 2`` generic dropped.**

    Pre-cast state on both engines: ONE Sami-shape carrier on p0's
    battlefield (the rider source), TWO vanilla Artifact-shape
    permanents pre-seated on p0's battlefield (the "scripted picker"
    per the design doc §7.3 — forcing the ≥1-controlled-artifact
    state without having to walk a full turn through casts of 2
    cheap artifacts). A second Sami in p0's hand to cast. p0's mana
    pool primed with {2}{R}{W} on both engines — the EXACT reduced
    cost: the {1} amount times the multiplier-of-2 subtracts {2} of
    generic from the {4}{R}{W} base, leaving generic=2 + RW colored
    pips.

    Cast on both engines:
      * **Python.** ``actions._cast_spell(state, 0, sami_id)``
        drives the full Python cast pipeline: selects empty
        targets, applies cost reductions
        (``apply_cost_reductions`` → ``_apply_external_cost_
        reductions``: walks the caster's battlefield, finds the
        Sami-shape carrier's ``external_cost_reductions``,
        evaluates ``PerControlled(IsArtifact()).matches`` against
        the caster's bf — 2 artifact-type permanents found, ``count
        >= 1`` → True — and reads ``PerControlled.multiplier`` (=
        count = 2; the affinity-style variable-multiplier path),
        applies ``ext.amount * condition.multiplier`` ({1} * 2 = 2
        generic dropped), the ``ManaCost.reduced(2)`` arithmetic
        at ``cards/base.py:298-305`` saturating-subs 2 generic →
        ``ManaCost(generic=2, colored=(('R', 1), ('W', 1)),
        x_pips=0)``), pays via ``auto_tap_for_cost`` (drains 2C +
        1R + 1W exactly), pushes the StackItem, increments
        ``spells_cast_this_turn``, fires IS_CAST.
      * **Rust.** ``cast_creature(sami_id, 0)`` drives the full
        Rust cast pipeline. The in-process call at
        ``state_ops_cast.rs:1167`` routes through
        ``apply_cost_reductions_rust(state, idx, printing, base)``
        at ``state_ops_legal.rs:764`` which calls
        ``apply_external_cost_reductions_rust`` FIRST (the
        externals-first ordering pinned in Phase 2 Cycle 1;
        mirrors Python ``actions.py:428-438``); that helper walks
        the caster's bf at ``state_ops_legal.rs:903``, finds the
        Sami-shape carrier's ``external_cost_reductions``,
        evaluates ``ExternalCondition::PerControlled { type_filter:
        TypeFilter::Artifact }`` — scans caster's bf at
        ``state_ops_legal.rs:933-955`` for permanents whose
        ``card_types`` contains ``"Artifact"`` — 2 here, returns
        ``(count >= 1, count)`` == ``(true, 2)`` (multiplier IS
        the count — the affinity-style scaling path), composes
        through ``cost.generic.saturating_sub(amt_clamped)`` at
        ``state_ops_legal.rs:967-969`` (``amt = 1 * 2 = 2``;
        ``amt_clamped = 2``; mirror of Python ``ManaCost.reduced``
        at ``cards/base.py:291-305``) → ManaCost(generic=2, R=1,
        W=1). Pays via ``auto_tap_pay_for_cost`` (drains 2C + 1R +
        1W), rehomes to the stack-source store, dispatches
        Event::Cast, increments ``spells_cast_this_turn``, pushes
        the StackItem.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players)
    AFTER the cast lands the spell on the stack.

    Critical bytes the probe pins:
      * Pool empty on both post-cast (the reduced {2}{R}{W} was
        paid exactly — Rust did NOT silently pay through 4
        colorless the way the pre-Phase-2 false-emission would
        have; both engines applied the SAME {2} = {1} * 2
        amount-times-multiplier reduction on the variable-
        multiplier path).
      * Sami (hand instance) off hand, on stack on both.
      * bf-resident Sami carrier still on the battlefield (the
        cost-payment scan is read-only).
      * Both seated artifacts still on p0's battlefield unchanged.

    **This is the case that diverges pre-Phase-2** (per design
    doc §3 / §7.3 admit table). The Phase-2 Cycle-2 substrate
    landed the byte-equal arithmetic on both sides via the
    ``apply_external_cost_reductions_rust`` helper + the widened
    admit predicate; this probe is the live-printing,
    actual-cast byte-equal proof on the variable-multiplier
    externals-axis condition variant — exactly the "round-46
    real-EoE-signal discipline" floor for the
    ``PerControlled(IsArtifact())`` affinity-style carrier. The
    Cycle-3 sibling (Uthros ``809d546c``) pinned the implicit-
    multiplier-1 ``NthSpellThisTurn`` path; together they exhaust
    the Phase-2 ExternalCondition variant surface byte-equal AND
    validate the multiplier arithmetic on the load-bearing
    affinity-style scaling path.
    """
    from mtg_bot.actions import _cast_spell
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import ManaCoin, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    real = _PRINTINGS.get("Sami, Wildcat Captain")
    if real is None:
        pytest.skip("Sami, Wildcat Captain absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Scripted picker (design doc §7.3): seat the Sami-shape
    # carrier FIRST on p0's bf, THEN 2 vanilla Artifact-shape
    # permanents on p0's battlefield on BOTH engines in lockstep.
    # The artifacts carry no cost_reductions, no abilities, no
    # keywords — pure type=Artifact carriers that satisfy the
    # IsArtifact filter in PerControlled's battlefield scan. The
    # injection order (Sami carrier first, then 2 artifacts, then
    # the hand Sami) keeps the per-zone object_id allocation in
    # lockstep across engines so the cross-engine field-view
    # comparison agrees on id slots.
    py_bf_sami = py.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bf_sami.summoning_sick = False
    py.battlefield.append(py_bf_sami)

    artifact_printing = CardPrinting(
        name="Scripted Artifact Token",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )
    py_artifacts: list = []
    for _ in range(2):
        py_a = py.new_object(
            artifact_printing, owner_id=0, zone=Zone.BATTLEFIELD,
        )
        py_a.summoning_sick = False
        py_a.etb_timestamp = py.next_timestamp
        py.next_timestamp += 1
        py.battlefield.append(py_a)
        py_artifacts.append(py_a)

    py_hand_sami = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py_hand_sami.summoning_sick = False
    py.players[0].hand.append(py_hand_sami)
    py.players[0].mana_pool.extend([
        ManaCoin(color="C"),
        ManaCoin(color="C"),
        ManaCoin(color="R"),
        ManaCoin(color="W"),
    ])

    # ---- Rust: register Sami-shape carrier in p0's battlefield
    # (zone 2) FIRST, then 2 Artifact-shape carriers, then the
    # hand Sami (zone 0). Same canonical dict for both Sami
    # injections.
    sami_dict = {
        "name": "Sami, Wildcat Captain",
        "card_types": ["Creature"],
        "subtypes": ["Human", "Artificer", "Rogue"],
        "mana_cost": {"generic": 4, "R": 1, "W": 1},
        "power": 4,
        "toughness": 4,
        "keywords": ["double_strike", "vigilance"],
        "external_cost_reductions": [
            {
                "amount": 1,
                "condition_kind": "per_controlled",
                "condition_args": ("artifact",),
            },
        ],
    }
    rs_bf_sami = rs.register_and_inject_object(
        sami_dict, 0, 2,  # controller=0, zone=2 (BATTLEFIELD)
    )
    artifact_dict = {
        "name": "Scripted Artifact Token",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
    }
    rs_artifact_ids: list = []
    for _ in range(2):
        rs_a = rs.register_and_inject_object(
            artifact_dict, 0, 2,  # controller=0, zone=2 (BATTLEFIELD)
        )
        rs_artifact_ids.append(rs_a)
    rs_hand_sami = rs.register_and_inject_object(
        sami_dict, 0, 0,  # controller=0, zone=0 (HAND)
    )
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "C", 1)
    rs.add_mana(0, "R", 1)
    rs.add_mana(0, "W", 1)

    # Pre-cast sanity: Sami carrier + 2 artifacts on p0's bf on both
    # engines (3 permanents total on p0's bf); stack empty on both.
    assert len(py.battlefield) == 3
    assert all(o.controller_id == 0 for o in py.battlefield)
    assert sum(
        1 for o in py.battlefield
        if "Artifact" in (o.printing.card_types or ())
    ) == 2
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # Pre-cast cross-engine field-view sanity — the scripted-picker
    # setup is byte-equal on BOTH engines before any cast fires. A
    # divergence here is a setup bug, not a Cycle-2 substrate bug —
    # surface it early.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-cast scripted-picker setup must be byte-equal across "
        f"engines (Sami bf carrier + 2 artifacts + hand Sami + "
        f"{{2}}{{R}}{{W}}-primed pool); got pre_diffs={pre_diffs}"
    )

    # ---- Drive the cast on both engines. ----
    _cast_spell(py, 0, py_hand_sami.id)
    ok = rs.cast_creature(rs_hand_sami, 0)
    assert ok is True, (
        "Rust cast_creature must succeed for Sami, Wildcat Captain "
        "at REDUCED {2}{R}{W} cost (with bf-resident Sami carrier + "
        "2 controlled artifacts) with a {2}{R}{W}-primed pool — the "
        "{1}-per-artifact * 2 = {2} external reduction MUST apply, "
        "and the apply_external_cost_reductions_rust helper MUST "
        "scan p0's bf, find the carrier's ExternalCostReduction(1, "
        "PerControlled(IsArtifact())), count 2 caster-controlled "
        "artifacts, evaluate count >= 1 → True with multiplier=2, "
        "and return ManaCost(generic=2, R=1, W=1). If this fails as "
        "'insufficient mana' it means the reduction did NOT fire — "
        "either the Phase-2 Cycle-2 substrate did not apply the "
        "external cost reduction on the live printing, or the "
        "caster-bf scan missed the seeded artifacts, or the "
        "multiplier arithmetic mis-counted."
    )

    # ---- Post-cast Python observables ----
    # Pool drained to empty: only {2}{R}{W} was paid (2 colorless +
    # 1 red + 1 white). If the reduction did NOT apply on Python
    # somehow, the cast would have failed at auto_tap_for_cost
    # (insufficient mana — we primed only 4 coins, not 6).
    assert py.players[0].mana_pool == [], (
        f"Python: pool must be empty post-cast (reduced cost "
        f"{{2}}{{R}}{{W}} paid exactly); got "
        f"{py.players[0].mana_pool}. A non-empty pool here means "
        f"the reduction over-applied (paid less than expected); a "
        f"failed-cast path would surface at auto_tap_for_cost."
    )
    # Hand emptied of the cast instance.
    assert all(o.id != py_hand_sami.id for o in py.players[0].hand)
    # bf carrier + 2 artifacts still present (3 permanents on p0's
    # bf post-cast — the cost-payment scan is read-only).
    assert any(o.id == py_bf_sami.id for o in py.battlefield)
    assert len(py.battlefield) == 3
    assert sum(
        1 for o in py.battlefield
        if "Artifact" in (o.printing.card_types or ())
    ) == 2
    # Stack carries Sami.
    assert len(py.stack) == 1
    assert py.stack[0].source.id == py_hand_sami.id

    # ---- Post-cast Rust observables ----
    rs_pool = rs.mana_pool_snapshot(0)
    assert all(v == 0 for v in rs_pool.values()), (
        f"Rust: pool must be empty post-cast (reduced cost paid "
        f"exactly); got {rs_pool}. A non-empty pool means the "
        f"reduction over-applied; a successful cast with a "
        f"non-empty pool would mean the Rust helper returned a "
        f"smaller cost than Python's apply_cost_reductions."
    )
    # Stack carries Sami. A successful cast with the {2}{R}{W}-only
    # primed pool is the load-bearing inline check: the Rust
    # external helper MUST have scanned p0's bf, found the
    # ExternalCostReduction(1, PerControlled(IsArtifact())) rider
    # on the carrier, counted 2 IsArtifact matches → multiplier=2,
    # evaluated count >= 1 → True, and returned the reduced
    # {2}{R}{W} cost via the saturating_sub of (1 * 2) = 2 generic;
    # otherwise auto_tap_pay_for_cost would have short-spent at the
    # {4}{R}{W} base.
    assert rs.stack_size() == 1

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Sami, Wildcat Captain reduced-cost lifecycle (cast with "
        f"bf-resident carrier + 2 controlled artifacts — the "
        f"{{1}}-per-artifact * multiplier=2 = {{2}} external "
        f"reduction applies via PerControlled(IsArtifact())) must "
        f"be byte-equal across the WHOLE field view on BOTH "
        f"engines; diffs={diffs}. This is the load-bearing "
        f"byte-equal that the Phase-2 Cycle-2 substrate FLIP rides "
        f"on for the affinity-style variable-multiplier external "
        f"carrier — a divergence here is an honest-stop signal."
    )
