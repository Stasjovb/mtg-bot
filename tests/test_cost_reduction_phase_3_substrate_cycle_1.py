"""cost-reduction substrate Phase 3 — Cycle 1 (substrate-only) pins.

**Lane.** ``feature/cost-reduction-phase-3-cycle-1-substrate-p1``
(2026-05-25).

Cycle 1 of the cost-reduction substrate Phase 3 campaign per
``docs/COST_REDUCTION_SUBSTRATE_PHASE_3_DESIGN.md`` (1,536 lines,
2026-05-25, merge ``2c18aae0``). Phase 3 admits sub-shape D — Fungal
Colossus (1 card / 13,165 17lands decks / 100% of the cost-reduction
REMAINING single-gated deck count post-Phase-2 closure ``4b683928``).
**Phase 3 closure drives the cost-reduction substrate single-gated row
from 1 card to 0 cards**, retiring the cost-reduction substrate from
the single-gated rollup entirely.

**Verify-first confirmation against live HEAD.**

* ``Condition`` enum at ``rust/src/cards.rs:9845`` — Phase 1's 2
  spell-local boolean variants (``AnotherSpellCastThisTurn`` +
  ``OpponentsControlAtLeast``); Phase 3 appends a third variant
  ``PerDifferentlyNamedLand`` (unit-shape, no payload).
* ``apply_cost_reductions_rust`` at ``rust/src/state_ops_legal.rs:764``
  — spell-local match arm extended in place (post-Phase-2 the helper
  already emits a Phase-2 externals scan FIRST). The 7 existing call
  sites stay structurally unchanged.
* Fungal Colossus's live parsed shape (verified at main ``2c18aae0``):
  ``cost_reductions=(CostReduction(amount=1,
  condition=PerDifferentlyNamedLand()),)``, ``external_cost_reductions
  =()``, vanilla 5/5 ``{6}{G}`` Creature with no other blocking
  feature (no keywords, no abilities, no spell_effect, no warp_cost,
  no kicker_cost, no impending_cost, no room_halves, no loyalty, no
  station_threshold, no dynamic_pt_formula, no ward_cost).
* Pre-Phase-3 ``_printing_is_bridge_pure_cost_reduction_creature``
  admit set is EXACTLY ``{Gigastorm Titan, Lashwhip Predator, Uthros
  Psionicist, Sami, Wildcat Captain}`` (4 cards — the Phase-1 +
  Phase-2 closure). Fungal Colossus is currently DECLINED; Cycle 1 is
  substrate-only and keeps Fungal Colossus DECLINED — Cycle 2 widens
  the admit predicate.

Substrate breakdown (sibling mirror of Phase 1 ``3683e62e`` + Phase 2
``5fa32697`` — same substrate→FLIP→per-card-probe cadence applied to
sub-shape D):

* **Cycle 1 (this slice — substrate-only).** New ``Condition::
  PerDifferentlyNamedLand`` unit-shape variant on the spell-local
  enum (NOT externals — Fungal's rider is on ``cost_reductions``,
  not ``external_cost_reductions``). New ``unique_land_names_count``
  helper that walks the caster's battlefield and counts distinctly-
  named lands (HashSet<&str> over ``printing.name`` filtered by the
  ``card_types`` contains-"Land" idiom). Extended ``apply_cost_
  reductions_rust``'s spell-local match arm to the ``(holds,
  multiplier)`` pair shape Phase-2's externals scan established
  (Phase-1 variants keep implicit ``multiplier == 1``; Phase-3
  variant returns ``(count >= 1, count)``). Extended ``parse_printing``
  cost_reductions arm with the ``per_differently_named_land``
  branch + hard-error teeth on arg drift. **Cycle 1 does NOT widen
  any Python admit predicate.** Fungal Colossus STAYS DECLINED post-
  Cycle-1 — the 9 sibling ``if printing.cost_reductions or printing.
  external_cost_reductions: return False`` guards in ``trajectory.py``
  + the unwidened ``_printing_is_bridge_pure_cost_reduction_creature``
  remain in place.

* **Cycle 2 (after — bridge round-trip + admit widen).** CardDef
  ``cost_reductions`` field docstring update + ``_card_def_to_python
  _printing`` reverse-arm extension (``per_differently_named_land``
  elif) + widened ``_cost_reduction_rule_is_phase1_or_3`` admit
  helper (Option A per design doc §5.4). **FLIPS Fungal Colossus
  DECLINED → ADMITTED**; this module's pin #4 (substrate-only
  invariant) inverts to an admit pin.

* **Cycle 3 (after — Fungal Colossus real-EoE probe).** Per-card
  real-EoE cross-engine byte-equality probe driving (a) the full-
  cost path (0 lands controlled), (b) the reduced-cost path (4
  distinctly-named lands → {4} reduction), (c) the multiplier-1
  path (4 lands sharing one name → {1} reduction; the set-semantic
  distinction). FLIPS Fungal Colossus covered_by_construction →
  PROBED.

* **Cycle 4 (optional — docs / SL / POOL_PARITY consolidation).**
  May fold into Cycle 3 if the diff stays small.

**What this module pins (substrate-only invariants).**

1. **Parser SoT.** Fungal Colossus parses to the exact
   ``CostReduction(amount=1, condition=PerDifferentlyNamedLand())``
   shape the design doc §2.1 claims — guards against parser drift
   while the new Rust substrate lands.
2. **Rust parse round-trip — ``PerDifferentlyNamedLand``.** A
   synthetic Fungal-shaped registry dict (the ``{"amount": 1,
   "condition_kind": "per_differently_named_land", "condition_args":
   ()}`` payload under a ``cost_reductions: [...]`` key) registers on
   Rust's ``parse_printing`` — no panic, no Err. The corresponding
   absent-args back-compat shape (``condition_args`` key omitted)
   also parses.
3. **Substrate-only invariant — Fungal Colossus STAYS DECLINED at
   the admit gate post-Cycle-1.** The 9 sibling ``if printing.
   cost_reductions or printing.external_cost_reductions: return
   False`` guards + the unwidened ``_printing_is_bridge_pure_cost_
   reduction_creature`` are load-bearing this cycle: admitting Fungal
   Colossus without the C2 bridge round-trip + admit widen would
   ship a guaranteed mana-pool divergence (Python applies the
   reduction; Rust has the field + evaluator but the Python bridge
   side has no reverse arm to feed it yet). Cycle 2 inverts this pin
   when the admit predicate widens. **The pin's failure means the
   substrate ALONE auto-flipped the admit gate** — which would
   replicate the Archenemy's Charm Cycle 1 honest-stop situation.
4. **Rust §2 teeth — arg-drift on `per_differently_named_land`
   hard-errors.** Negative-path parse pins on the spell-local arm:
   ``per_differently_named_land`` with non-empty args hard-errors at
   registry build. The ``silent no-op pipeline runs are pipeline
   bugs`` discipline + the §2 teeth.
5. **Live admit set is unchanged.** The number of bridge-admitted
   EoE printings under ``_printing_is_bridge_pure_cost_reduction_
   creature`` is identical post-Cycle-1 to pre-Cycle-1 (exactly the
   4 carriers — Gigastorm Titan + Lashwhip Predator + Uthros
   Psionicist + Sami, Wildcat Captain — admit; no Phase-3 card
   silently auto-grew under the substrate landing). The Rust
   ``Condition::PerDifferentlyNamedLand`` variant exists but the
   Python bridge half (Cycle 2) is not wired yet, so the live admit
   gate is exactly identical pre-/post-Cycle-1.

The Cycle 2 / Cycle 3 deliverables call out the inversion points so
reviewers tracking the cadence know exactly which pins flip when.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 — Parser SoT
# ---------------------------------------------------------------------------


def test_parser_sot_fungal_colossus_parses_to_phase3_cost_reduction():
    """Pin #1 — Fungal Colossus parser SoT.

    Fungal Colossus's printed surface form parses to exactly one
    ``CostReduction(amount=1, condition=PerDifferentlyNamedLand())``
    under ``printing.cost_reductions`` (NOT
    ``printing.external_cost_reductions``). Pre-existing on main;
    pinned here to guard against parser drift while the new Rust
    substrate lands.
    """
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand

    src = get_active_source().get_printings()
    p = src.get("Fungal Colossus")
    if p is None:
        pytest.skip("Fungal Colossus absent from active CardSource")

    # Vanilla 5/5 {6}{G} Creature shape — verified §1.2.
    assert p.card_types == ("Creature",)
    assert p.mana_cost_str == "{6}{G}"
    assert p.power == 5
    assert p.toughness == 5
    assert p.keywords == frozenset()

    # The cost_reductions rider — the canonical Phase-3 shape.
    assert p.external_cost_reductions == ()
    assert len(p.cost_reductions) == 1
    (rule,) = p.cost_reductions
    assert isinstance(rule, CostReduction)
    assert rule.amount == 1
    assert isinstance(rule.condition, PerDifferentlyNamedLand)

    # And NO other blocking riders — the design doc §2.2
    # "no other blocking feature" claim is preserved.
    assert not p.triggered_abilities
    assert not p.activated_abilities
    assert not p.static_abilities
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.kicker_cost is None
    assert p.impending_cost is None
    assert p.room_halves == ()
    assert p.loyalty is None
    assert p.station_threshold is None
    assert p.dynamic_pt_formula is None
    assert p.ward_cost is None


# ---------------------------------------------------------------------------
# Pin 2 — Rust parse round-trip
# ---------------------------------------------------------------------------


def test_rust_parser_accepts_per_differently_named_land_cost_reduction():
    """Pin #2 — Rust ``parse_printing`` accepts the Fungal shape.

    A synthetic Fungal-shaped registry dict — a ``Creature`` with
    ``cost_reductions=[{"amount": 1, "condition_kind":
    "per_differently_named_land", "condition_args": ()}]`` — registers
    on ``mtg_bot_engine.Registry.register_printing`` with no panic and
    no Err. The empty-tuple ``()`` is the canonical Phase-3 args shape;
    the Rust parser maps it to ``Condition::PerDifferentlyNamedLand``
    (unit variant).

    Round-trip-shape parity discipline (sibling of Phase 1 C1's pins
    #2 and #3 and Phase 2 C1's pins #2 and #3).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Phase 3 Cycle 1 Substrate Pin -- "
            "PerDifferentlyNamedLand carrier"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 6},
        "power": 5,
        "toughness": 5,
        "cost_reductions": [
            {
                "amount": 1,
                "condition_kind": "per_differently_named_land",
                "condition_args": (),
            },
        ],
    })
    assert isinstance(pid, int)


def test_rust_parser_accepts_per_differently_named_land_absent_args_back_compat():
    """Pin #2b — back-compat: the ``condition_args`` key may be
    omitted entirely for unit-shape variants (mirror of the Phase-1
    ``another_spell_cast_this_turn`` parse arm's same shape)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Phase 3 Cycle 1 Substrate Pin -- "
            "PerDifferentlyNamedLand absent condition_args key"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "cost_reductions": [
            {
                "amount": 1,
                "condition_kind": "per_differently_named_land",
            },
        ],
    })
    assert isinstance(pid, int)


def test_rust_parser_accepts_per_differently_named_land_with_explicit_empty_args():
    """Pin #2c — explicit ``()`` args tuple parses to the same variant.

    Both the absent-key and empty-tuple-args forms map to the same
    ``Condition::PerDifferentlyNamedLand`` Rust variant.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Phase 3 Cycle 1 Substrate Pin -- "
            "PerDifferentlyNamedLand explicit empty args"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "cost_reductions": [
            {
                "amount": 1,
                "condition_kind": "per_differently_named_land",
                "condition_args": (),
            },
        ],
    })
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# Pin 3 — Substrate-only invariant (the load-bearing closure marker)
# ---------------------------------------------------------------------------


def test_fungal_colossus_now_admits_at_admit_gate_post_cycle_2():
    """Pin #3a — INVERTED post-Cycle-2 — Fungal Colossus FLIP.

    **The load-bearing closure marker (Cycle 2 inversion).** Post-
    Phase-3-Cycle-2 (commit landing this slice), Fungal Colossus
    FLIPS DECLINED → ADMITTED at
    :func:`_printing_is_bridge_pure_cost_reduction_creature` AND at
    the deck-level :func:`_filter_deck_to_bridge_supported` OR-chain.
    Cycle 1's pin (substrate-only invariant — STAY DECLINED) inverts
    here when the bridge reverse-arm + widened admit predicate land.

    The simple-creature predicate STAYS False (its cost_reductions
    guard is sibling-load-bearing — the cost-reduction-aware
    predicate is the dedicated admit arm, a SIBLING of simple-creature
    not a widen).

    The Cycle 1 → Cycle 2 inversion is the documented closure pattern
    (mirror of Phase-1 Cycle 2 commit ``c370cee4`` / Phase-2 Cycle 2
    commit ``c370cee4``'s admit-widen).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    p = src.get("Fungal Colossus")
    if p is None:
        pytest.skip("Fungal Colossus absent from active CardSource")

    # The simple-creature arm STILL rejects (its cost_reductions
    # guard is sibling-load-bearing, not removed). Cycle 2 did NOT
    # widen the existing predicate — it widened the dedicated
    # cost-reduction-aware predicate.
    assert trajectory._printing_is_bridge_simple_creature(p) is False, (
        "Fungal Colossus must STAY DECLINED at the simple-creature "
        "admit gate post-Phase-3-Cycle-2 — the cost_reductions guard "
        "there is sibling-load-bearing."
    )
    # The widened dedicated admit predicate FLIPS True.
    assert (
        trajectory._printing_is_bridge_pure_cost_reduction_creature(p)
        is True
    ), (
        "Fungal Colossus must ADMIT at the widened "
        "_printing_is_bridge_pure_cost_reduction_creature predicate "
        "post-Phase-3-Cycle-2 (the C1 → C2 inversion). If False, the "
        "C2 admit-widen (the rename of "
        "_cost_reduction_rule_is_phase1 -> "
        "_cost_reduction_rule_is_phase1_or_3 + the PerDifferentlyNamedLand "
        "arm) didn't land."
    )
    # And the deck-level filter likewise — a 1-card deck containing
    # only Fungal Colossus must filter to (1-name, 1-CardDef-list)
    # post-Cycle-2.
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Fungal Colossus"], src,
    )
    assert filtered_names == ["Fungal Colossus"], (
        "Fungal Colossus must FLIP DECLINED→ADMITTED at the deck-level "
        "filter post-Phase-3-Cycle-2. Got "
        f"filtered_names={filtered_names!r}"
    )
    assert len(card_defs) == 1
    (cd,) = card_defs
    assert cd.name == "Fungal Colossus"
    assert cd.card_type == "Creature"
    # The CardDef carries the Phase-3 cost-reduction triple
    # round-trip-ready for the bridge.
    assert cd.cost_reductions == (
        (1, "per_differently_named_land", ()),
    ), f"unexpected cost_reductions tuple: {cd.cost_reductions!r}"
    assert cd.external_cost_reductions == ()


def test_phase_1_and_phase_2_carriers_still_admit_post_phase_3_cycle_1():
    """Pin #3b — Phase-1 + Phase-2 carriers STILL admit.

    The Phase-3 substrate landing is invariant on the Phase-1 +
    Phase-2 admit set: Gigastorm Titan + Lashwhip Predator + Uthros
    Psionicist + Sami, Wildcat Captain continue to pass
    ``_printing_is_bridge_pure_cost_reduction_creature`` post-Cycle-1.
    Failure here = the Phase-3 substrate landing accidentally
    regressed the Phase-1 + Phase-2 admit gate.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    for name in [
        "Gigastorm Titan",
        "Lashwhip Predator",
        "Uthros Psionicist",
        "Sami, Wildcat Captain",
    ]:
        p = src.get(name)
        if p is None:
            pytest.skip(f"{name} absent from active CardSource")
        assert (
            trajectory._printing_is_bridge_pure_cost_reduction_creature(p)
            is True
        ), (
            f"{name} (Phase-1 / Phase-2 carrier) must STILL admit at the "
            f"cost-reduction admit predicate post-Phase-3-Cycle-1. The "
            f"Phase-3 substrate landing must not regress the prior "
            f"phases' admit set."
        )


# ---------------------------------------------------------------------------
# Pin 4 — §2 Rust-side teeth (arg-drift hard-errors on the new variant)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        # Arg-count drift on `per_differently_named_land` (1 arg;
        # expects 0).
        (
            {
                "amount": 1,
                "condition_kind": "per_differently_named_land",
                "condition_args": ("creature",),
            },
            "takes 0 args",
        ),
        # Arg-count drift on `per_differently_named_land` (2 args;
        # expects 0).
        (
            {
                "amount": 1,
                "condition_kind": "per_differently_named_land",
                "condition_args": (1, 2),
            },
            "takes 0 args",
        ),
        # Non-tuple args drift on `per_differently_named_land`.
        (
            {
                "amount": 1,
                "condition_kind": "per_differently_named_land",
                "condition_args": "not-a-tuple",
            },
            "condition_args must be a tuple",
        ),
        # Phase-4+ token rejected — `and_combinator` doesn't exist yet.
        (
            {
                "amount": 1,
                "condition_kind": "and_combinator",
                "condition_args": (),
            },
            "and_combinator",
        ),
    ],
    ids=[
        "arg_count_drift_per_differently_named_land_takes_0_one",
        "arg_count_drift_per_differently_named_land_takes_0_two",
        "non_tuple_condition_args_rejected",
        "phase_4_unknown_token_rejected",
    ],
)
def test_rust_parser_rejects_out_of_phase_3_cost_reduction_shapes(
    payload: dict, expected_fragment: str
):
    """Pin #4 — §2 Rust-side teeth on the spell-local arm.

    Every out-of-Phase-1+3 ``cost_reductions`` entry shape hard-errors
    at registry build. Arg-count drifts on the new
    ``per_differently_named_land`` token AND any future-phase tokens
    (e.g. ``and_combinator``) all raise a ``ValueError`` with a
    message that points at the rejected token / shape — matching the
    ``silent no-op pipeline runs are pipeline bugs`` discipline.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    base = {
        "name": (
            "Cost-reduction Phase 3 Cycle 1 §2 teeth pin -- "
            f"{expected_fragment}"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "cost_reductions": [payload],
    }
    with pytest.raises(ValueError) as excinfo:
        reg.register_printing(base)
    assert expected_fragment in str(excinfo.value), (
        f"Expected the rejection message to mention "
        f"{expected_fragment!r}; got: {excinfo.value!s}"
    )


def test_rust_externals_arm_still_rejects_per_differently_named_land():
    """Pin #4b — Phase-3's spell-local token is REJECTED on the
    Phase-2 externals arm.

    ``per_differently_named_land`` is a SPELL-LOCAL token (lives on
    ``cost_reductions``), not an externals token. Putting it under
    the Phase-2 ``external_cost_reductions`` key must hard-error at
    registry build — Phase 3 did not silently widen the externals
    grammar.

    Sibling of the Phase-2 cycle-1 test
    ``phase_3_per_differently_named_land_rejected_on_externals`` —
    THAT test pre-existed; this one pins the post-Phase-3 invariant.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    base = {
        "name": (
            "Cost-reduction Phase 3 Cycle 1 §2 teeth pin -- "
            "per_differently_named_land on externals arm"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "external_cost_reductions": [
            {
                "amount": 1,
                "condition_kind": "per_differently_named_land",
                "condition_args": (),
            },
        ],
    }
    with pytest.raises(ValueError) as excinfo:
        reg.register_printing(base)
    assert "per_differently_named_land" in str(excinfo.value), (
        f"Expected the externals-side rejection to mention "
        f"'per_differently_named_land'; got: {excinfo.value!s}"
    )


# ---------------------------------------------------------------------------
# Pin 5 — Live admit-set bench-aggregate is unchanged
# ---------------------------------------------------------------------------


def test_live_cost_reduction_admit_count_is_five_post_cycle_2():
    """Pin #5 — INVERTED post-Cycle-2 — admit-set FLIPPED to 5.

    The set of live EoE printings that pass
    :func:`_printing_is_bridge_pure_cost_reduction_creature` post-
    Phase-3-Cycle-2 is EXACTLY ``{Gigastorm Titan, Lashwhip Predator,
    Uthros Psionicist, Sami, Wildcat Captain, Fungal Colossus}`` —
    the post-Phase-3-closure admit set (the design doc §7.4 pin 13
    "exactly 5 carriers" assertion). **The cost-reduction substrate
    single-gated row drops to zero post-Cycle-2; the substrate
    retires from the single-gated rollup entirely.** BLOCKED 56 → 55.

    Subsystem-attribution pin: exactly 5 EoE printings now pass the
    predicate post-Phase-3-Cycle-2 (was 4 post-Phase-3-Cycle-1; the
    +1 flip is Fungal Colossus).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    admitted = set()
    for name, p in src.items():
        if trajectory._printing_is_bridge_pure_cost_reduction_creature(p):
            admitted.add(name)

    # The post-Phase-3 admit set — exactly 5 carriers.
    expected = {
        "Gigastorm Titan",
        "Lashwhip Predator",
        "Uthros Psionicist",
        "Sami, Wildcat Captain",
        "Fungal Colossus",
    }
    assert admitted == expected, (
        f"Expected the cost-reduction admit set to be EXACTLY the 5 "
        f"post-Phase-3 carriers post-Cycle-2 (the FLIP); got "
        f"admitted={sorted(admitted)} expected={sorted(expected)}. "
        f"Fungal Colossus must FLIP DECLINED→ADMITTED in this cycle."
    )

    # Fungal Colossus FLIPPED — admitted post-Cycle-2.
    assert "Fungal Colossus" in admitted, (
        "Fungal Colossus must FLIP DECLINED→ADMITTED post-Cycle-2 "
        "(PerDifferentlyNamedLand is the Phase-3 sub-shape D rider; "
        "the widened _cost_reduction_rule_is_phase1_or_3 helper "
        "admits it)."
    )
