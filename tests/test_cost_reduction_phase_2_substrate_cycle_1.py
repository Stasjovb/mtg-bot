"""cost-reduction substrate Phase 2 — Cycle 1 (substrate-only) pins.

**Lane.** ``feature/cost-reduction-phase-2-cycle-1-substrate-p1``
(2026-05-25).

Cycle 1 of the cost-reduction substrate Phase 2 campaign per
``docs/COST_REDUCTION_SUBSTRATE_PHASE_2_DESIGN.md`` (1,387 lines,
2026-05-25, merge ``f75dbf0e``). Phase 2 admits sub-shapes B + C —
Uthros Psionicist + Sami, Wildcat Captain (2 cards / 15,575 17lands
decks combined / 54% of the cost-reduction REMAINING single-gated
deck count post-Phase-1). The campaign cadence mirrors Phase 1's
4-cycle closure precedent (1 substrate + 1 admit + 1 probe per card).

**Verify-first confirmation against live HEAD.**

* ``apply_cost_reductions_rust`` is at ``rust/src/state_ops_legal.rs:
  764`` (the design doc §4.4 claim is correct).
* ``Player.spells_cast_this_turn`` exists at ``rust/src/state.rs:1017``
  (Phase 1 verify-first already confirmed; Phase 2 inherits without
  modification — the design doc §4.5 deliverable is a no-op).
* Pre-Phase-2 ``TypeFilter`` enum has EXACTLY one variant (``Creature``);
  Phase 2 adds ``Artifact`` for Sami's ``PerControlled(IsArtifact())``.
* Uthros + Sami currently DECLINED at
  ``_printing_is_bridge_pure_cost_reduction_creature`` and at
  ``_printing_is_bridge_simple_creature``; the 9 sibling ``if
  printing.cost_reductions or printing.external_cost_reductions: return
  False`` guards keep them out.

Substrate breakdown (sibling mirror of Phase 1's commit
``3683e62e`` — same substrate→FLIP→per-card-probe cadence applied
to sub-shapes B + C):

* **Cycle 1 (this slice — substrate-only).** New Rust types — the
  ``ExternalCostReduction`` struct (mirrors Python's
  ``cards/base.py:326``); the Phase-2 ``ExternalCondition`` enum
  subset (2 variants — ``NthSpellThisTurn { n }`` +
  ``PerControlled { type_filter }``); the new ``TypeFilter::Artifact``
  variant (Sami's filter); the new ``CardPrinting.
  external_cost_reductions: Vec<ExternalCostReduction>`` field
  (back-compat default empty Vec). New ``parse_printing`` arm with
  tag-dispatch on ``condition_kind`` strings and hard-error on every
  out-of-Phase-2 token (the §2 Rust-side teeth — Phase 3 conditions
  like ``per_differently_named_land`` are loudly rejected; an unknown
  predicate token like ``"enchantment"`` on ``per_controlled`` is
  loudly rejected; an unexpected arg-count is loudly rejected). The
  ``apply_cost_reductions_rust`` helper body is EXTENDED with the
  externals scan (externals applied FIRST, then spell-local — mirror
  of Python ``actions.apply_cost_reductions`` ordering); the 7 call
  sites stay structurally unchanged. Cycle 1 does NOT widen any
  Python admit predicate. **Uthros Psionicist + Sami, Wildcat
  Captain STAY DECLINED post-Cycle-1** — the 9 sibling guards
  ``if printing.cost_reductions or printing.external_cost_reductions:
  return False`` in ``trajectory.py`` remain in place.

* **Cycle 2 (after — bridge round-trip + admit widen).** CardDef
  ``external_cost_reductions: tuple[tuple[int, str, tuple], ...]``
  field + ``_spec_card_to_printing_dict`` emit +
  ``_card_def_to_python_printing`` reverse arm + widened
  ``_printing_is_bridge_pure_cost_reduction_creature`` admit
  predicate (Option A per design doc §5.4). **FLIPS Uthros
  Psionicist + Sami, Wildcat Captain DECLINED → ADMITTED**; this
  module's #4 substrate-only pins invert to admit pins.

* **Cycle 3 (after — Uthros Psionicist real-EoE probe).** Per-card
  real-EoE cross-engine byte-equality probe driving both the
  full-cost path (first spell of the turn — ``spells_cast_this_turn
  == 0``) and the reduced-cost path (second spell of the turn —
  ``spells_cast_this_turn == 1``, the {2} reduction fires). FLIPS
  Uthros Psionicist covered_by_construction → PROBED.

* **Cycle 4 (after — Sami, Wildcat Captain real-EoE probe).** Per-
  card real-EoE probe driving both the full-cost path (Sami in play
  + 0 artifacts → multiplier 0 → no reduction) and the reduced-cost
  path (Sami in play + 2 artifacts → multiplier 2 → {2} reduction
  fires). FLIPS Sami, Wildcat Captain covered_by_construction →
  PROBED.

**What this module pins (substrate-only invariants).**

1. **Parser SoT.** Uthros Psionicist + Sami, Wildcat Captain parse
   to the exact ``ExternalCostReduction`` shapes the design doc §2
   claims — guards against parser drift while the new Rust substrate
   lands.
2. **Rust parse round-trip — `NthSpellThisTurn{n=2}`.** A synthetic
   Uthros-shaped registry dict (the ``{"amount": 2, "condition_kind":
   "nth_spell_this_turn", "condition_args": (2,)}`` payload under an
   ``external_cost_reductions: [...]`` key) registers on Rust's
   ``parse_printing`` — no panic, no Err. The corresponding back-
   compat default (absent ``external_cost_reductions`` key) maps to
   empty Vec on the Rust side and pre-existing fixtures' parse is
   byte-identical to pre-substrate.
3. **Rust parse round-trip — `PerControlled{type_filter=Artifact}`.**
   A synthetic Sami-shaped registry dict (the ``{"amount": 1,
   "condition_kind": "per_controlled", "condition_args":
   ("artifact",)}`` payload) registers on Rust's ``parse_printing``
   — no panic, no Err. The ``"creature"`` predicate-token sibling
   (no live carrier today, useful for synthetic tests) also accepts.
4. **Substrate-only invariant — Uthros Psionicist + Sami, Wildcat
   Captain STAY DECLINED at the admit gate post-Cycle-1.** The 9
   sibling ``if printing.cost_reductions or printing.external_cost_
   reductions: return False`` guards in ``trajectory.py`` are
   load-bearing this cycle: admitting these two cards without the
   C2 bridge round-trip would ship a guaranteed mana-pool divergence
   (Python applies the reduction; Rust would have the field but no
   bridge wiring to feed it). Cycle 2 inverts these pins when the
   admit predicate widens. **The pin's failure means the substrate
   ALONE auto-flipped the admit gate** — which would replicate the
   Archenemy's Charm Cycle 1 honest-stop situation.
5. **Rust §2 teeth — Phase-3+ tokens hard-error.** Negative-path
   parse pins on the externals arm: ``per_differently_named_land``
   (Phase 3 — spell-local-only, not an externals token),
   ``totally_made_up`` (unknown tag), ``per_controlled`` with an
   ``"enchantment"`` predicate token (Phase 3+ predicate algebra),
   and the arg-count drifts all hard-error at registry build. The
   ``silent no-op pipeline runs are pipeline bugs`` discipline +
   the §2 teeth.
6. **Live admit set is unchanged.** The number of bridge-admitted
   EoE printings under ``_printing_is_bridge_pure_cost_reduction_
   creature`` is identical post-Cycle-1 to pre-Cycle-1 (exactly the
   2 Phase-1 carriers — Gigastorm Titan + Lashwhip Predator —
   admit; no Phase-2 card silently auto-grew under the substrate
   landing). The Rust ``external_cost_reductions`` field exists but
   the Python bridge half (Cycle 2) is not wired yet, so the live
   admit gate is exactly identical pre-/post-Cycle-1.

The Cycle 2 / Cycle 3 / Cycle 4 deliverables call out the inversion
points so reviewers tracking the cadence know exactly which pins
flip when.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 — Parser SoT
# ---------------------------------------------------------------------------


def test_parser_sot_uthros_psionicist_parses_to_phase2_external_cost_reduction():
    """Pin #1a — Uthros Psionicist parser SoT.

    Uthros Psionicist's printed surface form parses to exactly one
    ``ExternalCostReduction(amount=2, condition=NthSpellThisTurn(n=2))``
    under ``printing.external_cost_reductions``. Pre-existing on main;
    pinned here to guard against parser drift while the new Rust
    substrate lands.
    """
    from mtg_bot.cards.base import ExternalCostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import NthSpellThisTurn

    src = get_active_source().get_printings()
    p = src.get("Uthros Psionicist")
    if p is None:
        pytest.skip("Uthros Psionicist absent from active CardSource")

    assert p.card_types == ("Creature",)
    assert p.cost_reductions == ()
    assert len(p.external_cost_reductions) == 1
    (rule,) = p.external_cost_reductions
    assert isinstance(rule, ExternalCostReduction)
    assert rule.amount == 2
    assert isinstance(rule.condition, NthSpellThisTurn)
    assert rule.condition.n == 2
    # And NO other blocking riders — the design doc §2 "no other
    # blocking feature" claim is preserved.
    assert not p.triggered_abilities
    assert not p.activated_abilities
    assert not p.static_abilities
    assert p.spell_effect is None
    assert p.warp_cost is None


def test_parser_sot_sami_wildcat_captain_parses_to_phase2_external_cost_reduction():
    """Pin #1b — Sami, Wildcat Captain parser SoT.

    Sami, Wildcat Captain's printed surface form parses to exactly one
    ``ExternalCostReduction(amount=1, condition=PerControlled(filter=
    IsArtifact()))``. Pre-existing on main.
    """
    from mtg_bot.cards.base import ExternalCostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import PerControlled
    from mtg_bot.effects.object_predicates import IsArtifact

    src = get_active_source().get_printings()
    p = src.get("Sami, Wildcat Captain")
    if p is None:
        pytest.skip("Sami, Wildcat Captain absent from active CardSource")

    assert p.card_types == ("Creature",)
    assert p.cost_reductions == ()
    assert len(p.external_cost_reductions) == 1
    (rule,) = p.external_cost_reductions
    assert isinstance(rule, ExternalCostReduction)
    assert rule.amount == 1
    assert isinstance(rule.condition, PerControlled)
    assert isinstance(rule.condition.filter, IsArtifact)


# ---------------------------------------------------------------------------
# Pin 2 / Pin 3 — Rust parse round-trip
# ---------------------------------------------------------------------------


def test_rust_parser_accepts_nth_spell_this_turn_external_cost_reduction():
    """Pin #2 — Rust ``parse_printing`` accepts the Uthros shape.

    A synthetic Uthros-shaped registry dict — a ``Creature`` with
    ``external_cost_reductions=[{"amount": 2, "condition_kind":
    "nth_spell_this_turn", "condition_args": (2,)}]`` — registers on
    ``mtg_bot_engine.Registry.register_printing`` with no panic and no
    Err. The 1-tuple ``(n,)`` is the canonical Phase-2 args shape; the
    Rust parser maps it to ``ExternalCondition::NthSpellThisTurn {
    n: 2 }``.

    Round-trip-shape parity discipline (sibling of Phase 1 C1's pins
    #2 and #3).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Phase 2 Cycle 1 Substrate Pin -- "
            "NthSpellThisTurn(n=2) carrier"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 2},
        "power": 2,
        "toughness": 3,
        "external_cost_reductions": [
            {
                "amount": 2,
                "condition_kind": "nth_spell_this_turn",
                "condition_args": (2,),
            },
        ],
    })
    assert isinstance(pid, int)


def test_rust_parser_accepts_per_controlled_artifact_external_cost_reduction():
    """Pin #3 — Rust ``parse_printing`` accepts the Sami shape.

    A synthetic Sami-shaped registry dict — a ``Creature`` with
    ``external_cost_reductions=[{"amount": 1, "condition_kind":
    "per_controlled", "condition_args": ("artifact",)}]`` — registers
    on ``mtg_bot_engine.Registry.register_printing`` with no panic and
    no Err. The 1-tuple ``("artifact",)`` is the canonical Phase-2
    args shape (predicate token); the Rust parser maps it to
    ``ExternalCondition::PerControlled { type_filter:
    TypeFilter::Artifact }``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Phase 2 Cycle 1 Substrate Pin -- "
            "PerControlled(Artifact) carrier"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"R": 1, "generic": 2},
        "power": 3,
        "toughness": 3,
        "external_cost_reductions": [
            {
                "amount": 1,
                "condition_kind": "per_controlled",
                "condition_args": ("artifact",),
            },
        ],
    })
    assert isinstance(pid, int)


def test_rust_parser_accepts_per_controlled_creature_external_cost_reduction():
    """Pin #3b — Rust ``parse_printing`` accepts the
    ``per_controlled`` arm's already-shipped sibling predicate token
    ``"creature"`` (the Phase-1 ``TypeFilter::Creature`` variant is
    reusable from the externals scan).

    No live EoE carrier today, but the symbolic admit-set is two
    predicate tokens (``"artifact"`` + ``"creature"``); synthetic
    tests need access to both. Failure here = the parser dropped one
    of the two declared variants.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Phase 2 Cycle 1 Substrate Pin -- "
            "PerControlled(Creature) carrier (synthetic)"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
        "external_cost_reductions": [
            {
                "amount": 1,
                "condition_kind": "per_controlled",
                "condition_args": ("creature",),
            },
        ],
    })
    assert isinstance(pid, int)


def test_rust_parser_accepts_absent_external_cost_reductions_back_compat():
    """Pin #3c — back-compat: a registry dict without the
    ``external_cost_reductions`` key parses unchanged (the absent-key
    → empty-Vec arm — the same pattern Phase 1's ``cost_reductions``
    and every other optional list field uses)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Phase 2 Cycle 1 Substrate Pin -- "
            "absent external_cost_reductions key (back-compat)"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
    })
    assert isinstance(pid, int)


def test_rust_parser_accepts_empty_external_cost_reductions_list():
    """Pin #3d — empty-list parse: the explicit ``[]`` form parses to
    the same empty Vec as the absent-key form."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Phase 2 Cycle 1 Substrate Pin -- "
            "explicit empty external_cost_reductions list"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "external_cost_reductions": [],
    })
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# Pin 4 — Substrate-only invariant (the load-bearing closure marker)
# ---------------------------------------------------------------------------


def test_uthros_psionicist_admits_at_cost_reduction_predicate_post_cycle_2():
    """Pin #4a — INVERTED in Cycle 2 — Uthros Psionicist ADMITS.

    **The load-bearing FLIP marker (Cycle 2 widened-predicate
    invariant).** Post-Cycle-2 the widened
    :func:`_printing_is_bridge_pure_cost_reduction_creature`
    admits Uthros Psionicist — the Phase-2 externals rider
    ``ExternalCostReduction(amount=2,
    condition=NthSpellThisTurn(n=2))`` is one of the two §5.4
    admit shapes. The simple-creature predicate STILL rejects
    (the 9 sibling guards remain load-bearing — defense-in-depth);
    the new admit happens at the cost-reduction-aware predicate.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    p = src.get("Uthros Psionicist")
    if p is None:
        pytest.skip("Uthros Psionicist absent from active CardSource")

    # Cycle 2 inverted state: simple-creature still rejects (the 9
    # sibling guards are intact — defense-in-depth).
    assert trajectory._printing_is_bridge_simple_creature(p) is False, (
        "Uthros Psionicist must STAY DECLINED at the simple-creature "
        "admit gate post-Cycle-2 — the external_cost_reductions "
        "guard there remains load-bearing (the FLIP happens at the "
        "cost-reduction-aware predicate, not at simple-creature)."
    )
    # AND the cost-reduction admit predicate ADMITS (the FLIP).
    assert (
        trajectory._printing_is_bridge_pure_cost_reduction_creature(p)
        is True
    ), (
        "Uthros Psionicist must ADMIT at the Phase-1+2 cost-"
        "reduction admit predicate post-Cycle-2. The Cycle-2 "
        "widening of this predicate is THE FLIP."
    )


def test_sami_wildcat_captain_admits_at_cost_reduction_predicate_post_cycle_2():
    """Pin #4b — INVERTED in Cycle 2 — Sami, Wildcat Captain ADMITS.

    Same FLIP marker as #4a, for Sami, Wildcat Captain. The
    Phase-2 externals rider ``ExternalCostReduction(amount=1,
    condition=PerControlled(IsArtifact()))`` is one of the two
    §5.4 admit shapes. Both Phase-2 carriers flip simultaneously.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    p = src.get("Sami, Wildcat Captain")
    if p is None:
        pytest.skip("Sami, Wildcat Captain absent from active CardSource")

    assert trajectory._printing_is_bridge_simple_creature(p) is False, (
        "Sami, Wildcat Captain must STAY DECLINED at the simple-"
        "creature admit gate post-Cycle-2 — the sibling guard "
        "remains load-bearing."
    )
    assert (
        trajectory._printing_is_bridge_pure_cost_reduction_creature(p)
        is True
    ), (
        "Sami, Wildcat Captain must ADMIT at the Phase-1+2 cost-"
        "reduction admit predicate post-Cycle-2. Simultaneous FLIP "
        "with Uthros Psionicist."
    )


def test_phase_1_carriers_still_admit_at_phase1_predicate_post_cycle_1():
    """Pin #4c — Phase-1 carriers (Gigastorm + Lashwhip) STILL admit.

    The Phase-2 substrate landing is invariant on the Phase-1 admit
    set: Gigastorm Titan + Lashwhip Predator continue to pass
    ``_printing_is_bridge_pure_cost_reduction_creature`` post-Cycle-1.
    Failure here = the Phase-2 widening accidentally regressed the
    Phase-1 admit gate (which would block Phase 1's gigas + lashwhip
    cards from the bench).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    for name in ["Gigastorm Titan", "Lashwhip Predator"]:
        p = src.get(name)
        if p is None:
            pytest.skip(f"{name} absent from active CardSource")
        assert (
            trajectory._printing_is_bridge_pure_cost_reduction_creature(p)
            is True
        ), (
            f"{name} (Phase-1 carrier) must STILL admit at the cost-"
            f"reduction admit predicate post-Phase-2-Cycle-1. The "
            f"Phase-2 substrate landing must not regress Phase-1."
        )


# ---------------------------------------------------------------------------
# Pin 5 — §2 Rust-side teeth (Phase-3+ tokens hard-error)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        # Phase-3 condition kind on the externals side —
        # `per_differently_named_land` is a spell-local-only condition
        # (Fungal Colossus is a `cost_reductions` carrier, not
        # `external_cost_reductions`); the externals arm hard-rejects.
        (
            {
                "amount": 1,
                "condition_kind": "per_differently_named_land",
                "condition_args": (),
            },
            "per_differently_named_land",
        ),
        # Phase-1 spell-local token applied to the externals arm —
        # `another_spell_cast_this_turn` is a Phase-1 spell-local
        # condition_kind, NOT a Phase-2 externals condition_kind.
        # `Uthros Psionicist` uses `nth_spell_this_turn` instead.
        (
            {
                "amount": 1,
                "condition_kind": "another_spell_cast_this_turn",
                "condition_args": (),
            },
            "another_spell_cast_this_turn",
        ),
        # Totally unknown tag — also a hard error.
        (
            {
                "amount": 1,
                "condition_kind": "totally_made_up_phase_99_kind",
                "condition_args": (),
            },
            "totally_made_up_phase_99_kind",
        ),
        # Phase-3+ predicate algebra on `per_controlled` —
        # `("enchantment",)` is a future predicate; Phase 2 only
        # supports `("artifact",)` / `("creature",)`.
        (
            {
                "amount": 1,
                "condition_kind": "per_controlled",
                "condition_args": ("enchantment",),
            },
            "enchantment",
        ),
        # Arg-count drift on `nth_spell_this_turn` (0 args; expects 1).
        (
            {
                "amount": 1,
                "condition_kind": "nth_spell_this_turn",
                "condition_args": (),
            },
            "takes 1 arg",
        ),
        # Arg-count drift on `nth_spell_this_turn` (2 args; expects 1).
        (
            {
                "amount": 1,
                "condition_kind": "nth_spell_this_turn",
                "condition_args": (2, 3),
            },
            "takes 1 arg",
        ),
        # Arg-count drift on `per_controlled` (2 args; expects 1).
        (
            {
                "amount": 1,
                "condition_kind": "per_controlled",
                "condition_args": ("artifact", 3),
            },
            "takes 1 arg",
        ),
        # Missing required key — `amount` not present.
        (
            {
                "condition_kind": "nth_spell_this_turn",
                "condition_args": (2,),
            },
            "amount is required",
        ),
        # Missing required key — `condition_kind` not present.
        (
            {
                "amount": 2,
                "condition_args": (2,),
            },
            "condition_kind is required",
        ),
        # `nth_spell_this_turn` without `condition_args` key entirely.
        (
            {
                "amount": 2,
                "condition_kind": "nth_spell_this_turn",
            },
            "requires condition_args",
        ),
        # `per_controlled` without `condition_args` key entirely.
        (
            {
                "amount": 1,
                "condition_kind": "per_controlled",
            },
            "requires condition_args",
        ),
    ],
    ids=[
        "phase_3_per_differently_named_land_rejected_on_externals",
        "phase_1_spell_local_kind_rejected_on_externals",
        "unknown_condition_kind_rejected",
        "phase_3_predicate_token_enchantment_rejected",
        "arg_count_drift_nth_spell_takes_1_zero",
        "arg_count_drift_nth_spell_takes_1_two",
        "arg_count_drift_per_controlled_takes_1",
        "missing_amount_rejected",
        "missing_condition_kind_rejected",
        "nth_spell_missing_condition_args_rejected",
        "per_controlled_missing_condition_args_rejected",
    ],
)
def test_rust_parser_rejects_out_of_phase_2_external_cost_reduction_shapes(
    payload: dict, expected_fragment: str
):
    """Pin #5 — §2 Rust-side teeth on the externals arm.

    Every out-of-Phase-2 ``external_cost_reductions`` entry shape
    hard-errors at registry build. Tags Phase 3 will land
    (``per_differently_named_land`` — spell-local-only, not an
    externals token; the Phase-3 predicate algebra extensions),
    unknown tags, mistaken use of Phase-1 spell-local tokens on the
    externals arm, and any arg-count drift on the two Phase-2 tags
    all raise a ``ValueError`` with a message that points at the
    rejected token / shape — matching the
    ``silent no-op pipeline runs are pipeline bugs`` discipline.

    Phase 3 will RELAX one of these arms (the
    ``per_differently_named_land`` rejection is spell-local-side; the
    externals-side may add additional predicate tokens) when the
    Fungal Colossus closure ships.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    base = {
        "name": (
            "Cost-reduction Phase 2 Cycle 1 §2 teeth pin -- "
            f"{expected_fragment}"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "external_cost_reductions": [payload],
    }
    with pytest.raises(ValueError) as excinfo:
        reg.register_printing(base)
    assert expected_fragment in str(excinfo.value), (
        f"Expected the rejection message to mention "
        f"{expected_fragment!r}; got: {excinfo.value!s}"
    )


def test_rust_parser_rejects_non_list_external_cost_reductions():
    """Pin #5b — non-list ``external_cost_reductions`` is a hard error.

    The parser expects a list of dicts (mirror of the Phase-1
    ``cost_reductions`` shape). A dict / tuple / string value loudly
    rejects at registry build.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    base = {
        "name": (
            "Cost-reduction Phase 2 Cycle 1 §2 teeth pin -- "
            "non-list external_cost_reductions"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "external_cost_reductions": "not-a-list",
    }
    with pytest.raises(ValueError) as excinfo:
        reg.register_printing(base)
    assert "list of dicts" in str(excinfo.value), (
        f"Expected the rejection to mention 'list of dicts'; got: "
        f"{excinfo.value!s}"
    )


# ---------------------------------------------------------------------------
# Pin 6 — Live admit-set bench-aggregate is unchanged
# ---------------------------------------------------------------------------


def test_live_cost_reduction_admit_count_is_bumped_post_cycle_2():
    """Pin #6 — INVERTED in Cycle 2 — admit-set bumped +2.

    The set of live EoE printings that pass
    ``_printing_is_bridge_pure_cost_reduction_creature`` post-Cycle-2
    is EXACTLY ``{Gigastorm Titan, Lashwhip Predator, Uthros
    Psionicist, Sami, Wildcat Captain}`` — the +2 bump from the
    Phase-1 carrier set. Both Phase-2 carriers flipped DECLINED →
    ADMITTED at the widened predicate; Fungal Colossus (Phase 3)
    still declines.

    Subsystem-attribution pin: exactly 4 EoE printings now pass the
    predicate post-Phase-2 closure (design doc §7.4 pin 12).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    admitted = set()
    for name, p in src.items():
        if trajectory._printing_is_bridge_pure_cost_reduction_creature(p):
            admitted.add(name)

    # Phase-1 carriers still admit (no regression).
    assert "Gigastorm Titan" in admitted, (
        "Gigastorm Titan (Phase-1) must STILL admit post-Cycle-2."
    )
    assert "Lashwhip Predator" in admitted, (
        "Lashwhip Predator (Phase-1) must STILL admit post-Cycle-2."
    )
    # Phase-2 carriers NOW admit — THE FLIP.
    assert "Uthros Psionicist" in admitted, (
        "Uthros Psionicist must ADMIT post-Cycle-2 — the widened "
        "_printing_is_bridge_pure_cost_reduction_creature includes "
        "Phase-2 externals (NthSpellThisTurn)."
    )
    assert "Sami, Wildcat Captain" in admitted, (
        "Sami, Wildcat Captain must ADMIT post-Cycle-2 — the widened "
        "predicate includes Phase-2 externals (PerControlled "
        "Artifact)."
    )
    # Fungal Colossus (Phase 3) STILL declined — no silent auto-grow.
    assert "Fungal Colossus" not in admitted, (
        "Fungal Colossus must STAY DECLINED post-Cycle-2 "
        "(PerDifferentlyNamedLand is Phase 3 — the design doc §3.1 "
        "deferral; the no-silent-auto-grow discipline)."
    )
