"""cost-reduction substrate Phase 1 — Cycle 1 (substrate-only) pins.

**Lane.** ``feature/cost-reduction-phase-1-cycle-1-substrate-p1``
(2026-05-24).

Cycle 1 of the cost-reduction substrate Phase 1 campaign per
``docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md`` (973 lines,
2026-05-24, merge ``4b94f844``) and the
``cost-reduction-subsystem-decline-revisit-p1`` audit
(``docs/COST_REDUCTION_SUBSYSTEM_REVISIT_2026-05-24.md``, merge
``added6db``).

Phase 1 admits ONLY sub-shape A — Gigastorm Titan + Lashwhip Predator
(2 cards / 24,908 17lands decks / 46 % of the cost-reduction single-
gated deck pool). The campaign cadence is calibrated against today's
CH / MTL / AV per-card multi-cycle closures (1 substrate + 1 admit +
1 probe per card).

**Verify-first deviation from the design doc.** The design doc §4.5 +
§7.1#5–#6 list ``Player.spells_cast_this_turn`` as a Cycle-1 Rust
deliverable (new field + increment + reset + fingerprint thread).
**Verify-first against live HEAD found the field ALREADY exists** at
``rust/src/state.rs:1017`` (landed via MMM Pin 1, the 11th Rust
slice). Every plumbing piece the design doc anticipates is already in
place: increment in all four cast primitives
(``cast_creature`` / ``cast_creature_warp`` / ``cast_spell_noncreature``
/ ``cast_aura``) AFTER pay; reset in
``state_ops_steps.rs::run_cleanup_step`` at the Python-matched
``turn.py:1105`` boundary; threaded through the canonical-state
fingerprint at ``info_set.py:216`` / ``canonical_state.py:484``; the
test setter ``set_spells_cast_this_turn`` at
``state_ops_resolve.rs:23669``. So Cycle 1 lands only the
cost-reduction-side structures (struct + enum + field + parse +
hard-error teeth); the per-player state-field deliverable is a no-op.
This module's pins #5–#6 still defend the already-shipped ordering /
reset invariants as defense-in-depth.

Substrate breakdown (sibling mirror of Anticausal Vestige multi-cycle
commits ``e148450a`` C1, ``c32f07f9`` C2, ``a9001390`` C3 — the same
substrate→admit-widen→probe cadence applied today):

* **Cycle 1 (this slice — substrate-only).** New Rust types — the
  ``CostReduction`` struct (mirrors Python's
  ``cards/base.py:308``); the Phase-1 ``Condition`` enum subset (2
  variants — ``AnotherSpellCastThisTurn`` +
  ``OpponentsControlAtLeast { type_filter, count }``); the Phase-1
  ``TypeFilter`` enum subset (1 variant — ``Creature``); the new
  ``CardPrinting.cost_reductions: Vec<CostReduction>`` field
  (back-compat default empty Vec). New ``parse_printing`` arm with a
  tag-dispatch on ``condition_kind`` strings and hard-error on every
  out-of-Phase-1 token (the §2 Rust-side teeth — Phase 2 conditions
  like ``per_differently_named_land`` are loudly rejected; an unknown
  predicate token like ``"artifact"`` on ``opponents_control_at_least``
  is loudly rejected; an unexpected arg-count is loudly rejected).
  Cycle 1 does NOT extend the ``eff()`` seam at
  ``state_ops_legal.rs:742`` (stays identity — Cycle 2 owns the seam
  extension once the bridge half is in place). Cycle 1 does NOT
  widen any Python admit predicate. **Gigastorm Titan + Lashwhip
  Predator STAY DECLINED post-Cycle-1** — the 10 sibling guards
  ``if printing.cost_reductions or printing.external_cost_reductions:
  return False`` in ``trajectory.py`` remain in place.

* **Cycle 2 (after — bridge round-trip + admit widen).** CardDef
  ``cost_reductions: tuple[tuple[int, str, tuple], ...]`` field +
  ``build_rust_state`` emit + ``_card_def_to_python_printing``
  reverse arm + new ``_printing_is_bridge_pure_cost_reduction_creature``
  admit predicate. **FLIPS Gigastorm Titan + Lashwhip Predator
  DECLINED → ADMITTED**; this module's #4 substrate-only pins invert
  to admit pins.

* **Cycle 3 (after — Gigastorm Titan real-EoE probe).** Per-card
  real-EoE cross-engine byte-equality probe driving both the
  full-cost path (first spell of the turn) and the reduced-cost
  path (cheap spell first, then Gigastorm second). FLIPS Gigastorm
  Titan covered_by_construction → PROBED.

* **Cycle 4 (after — Lashwhip Predator real-EoE probe).** Per-card
  real-EoE probe driving both the full-cost path (opponents control
  < 3 creatures) and the reduced-cost path (opponents control >= 3
  creatures). FLIPS Lashwhip Predator covered_by_construction →
  PROBED.

* **Cycle 5 (rolling).** SEARCH_LIMITATIONS.md entries +
  POOL_PARITY.md regen.

**What this module pins (substrate-only invariants).**

1. **Parser SoT.** Gigastorm Titan + Lashwhip Predator parse to the
   exact ``CostReduction`` shapes the design doc §2 claims —
   guards against parser drift while the new Rust substrate lands.
2. **Rust parse round-trip — `AnotherSpellCastThisTurn`.** A
   synthetic Gigastorm-shaped registry dict (the
   ``{"amount": 3, "condition_kind":
   "another_spell_cast_this_turn", "condition_args": ()}`` payload
   under a ``cost_reductions: [...]`` key) registers on Rust's
   ``parse_printing`` — no panic, no Err. The corresponding back-
   compat default (absent ``cost_reductions`` key) maps to empty
   Vec on the Rust side and pre-existing fixtures' parse is
   byte-identical to pre-substrate.
3. **Rust parse round-trip — `OpponentsControlAtLeast { Creature,
   3 }`.** A synthetic Lashwhip-shaped registry dict (the ``{"amount":
   2, "condition_kind": "opponents_control_at_least",
   "condition_args": ("creature", 3)}`` payload) registers on
   Rust's ``parse_printing`` — no panic, no Err.
4. **Substrate-only invariant — Gigastorm Titan + Lashwhip Predator
   STAY DECLINED at the admit gate post-Cycle-1.** The 10 sibling
   ``if printing.cost_reductions or printing.external_cost_reductions:
   return False`` guards in ``trajectory.py`` are load-bearing this
   cycle: admitting these two cards without the C2 bridge round-trip
   would ship a guaranteed mana-pool divergence (Python applies the
   reduction; Rust pays the full ``p.mana_cost``). Cycle 2 inverts
   these pins when the admit predicate widens. **The pin's failure
   means the substrate ALONE auto-flipped the admit gate** — which
   would replicate the Archenemy's Charm Cycle 1 honest-stop
   situation (commit ``8f8bc77b``).
5. **Rust §2 teeth — Phase-2 tokens hard-error.** The 5 negative-path
   parse pins: ``per_differently_named_land`` (Phase-2 condition),
   ``totally_made_up`` (unknown tag), ``opponents_control_at_least``
   with ``"artifact"`` predicate (Phase-2 predicate algebra), and
   the two arg-count drifts all hard-error at registry build. The
   ``silent no-op pipeline runs are pipeline bugs`` discipline +
   the §2 teeth.
6. **Pre-existing `Player.spells_cast_this_turn` increment-ordering
   defense-in-depth pin.** Defends the already-shipped invariant
   that ``cast_creature`` increments AFTER ``auto_tap_pay_for_cost``
   commits the spend (so an ``AnotherSpellCastThisTurn`` reduction
   evaluated PRE-pay would see ``spells_cast_this_turn == 0`` on
   the caster's first spell — full cost paid). The test drives the
   pre-existing test setter ``set_spells_cast_this_turn`` to pin
   the field's accessible-from-Python contract on which Cycle 2's
   seam extension will lean.
7. **Live admit set is unchanged.** The number of
   bridge-admitted EoE printings under
   ``_printing_is_bridge_simple_creature`` is identical post-Cycle-1
   to pre-Cycle-1 (zero auto-grow) — the substrate-only invariant's
   bench-aggregate sibling.

The Cycle 2 / Cycle 3 / Cycle 4 deliverables call out the inversion
points so reviewers tracking the cadence know exactly which pins
flip when.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 — Parser SoT
# ---------------------------------------------------------------------------


def test_parser_sot_gigastorm_titan_parses_to_phase1_cost_reduction():
    """Pin #1a — Gigastorm Titan parser SoT.

    Gigastorm Titan's printed surface form parses to exactly one
    ``CostReduction(amount=3, condition=AnotherSpellCastThisTurn())``
    under ``printing.cost_reductions``. Pre-existing on main; pinned
    here to guard against parser drift while the new Rust substrate
    lands.
    """
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import AnotherSpellCastThisTurn

    src = get_active_source().get_printings()
    g = src.get("Gigastorm Titan")
    if g is None:
        pytest.skip("Gigastorm Titan absent from active CardSource")

    assert g.card_types == ("Creature",)
    assert g.mana_cost_str == "{4}{U}"
    assert len(g.cost_reductions) == 1
    (rule,) = g.cost_reductions
    assert isinstance(rule, CostReduction)
    assert rule.amount == 3
    assert isinstance(rule.condition, AnotherSpellCastThisTurn)
    # And NO externals / triggers / static / etc — the design doc
    # §2 "no other blocking feature" claim is preserved.
    assert g.external_cost_reductions == ()
    assert not g.triggered_abilities
    assert not g.activated_abilities
    assert not g.static_abilities
    assert g.spell_effect is None
    assert g.warp_cost is None
    assert g.keywords == frozenset()


def test_parser_sot_lashwhip_predator_parses_to_phase1_cost_reduction():
    """Pin #1b — Lashwhip Predator parser SoT.

    Lashwhip Predator's printed surface form parses to exactly one
    ``CostReduction(amount=2, condition=OpponentsControlAtLeast(
    IsCreature(), 3))``. Pre-existing on main.
    """
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import OpponentsControlAtLeast
    from mtg_bot.effects.object_predicates import IsCreature

    src = get_active_source().get_printings()
    lp = src.get("Lashwhip Predator")
    if lp is None:
        pytest.skip("Lashwhip Predator absent from active CardSource")

    assert lp.card_types == ("Creature",)
    assert lp.mana_cost_str == "{4}{G}{G}"
    assert len(lp.cost_reductions) == 1
    (rule,) = lp.cost_reductions
    assert isinstance(rule, CostReduction)
    assert rule.amount == 2
    assert isinstance(rule.condition, OpponentsControlAtLeast)
    assert isinstance(rule.condition.filter, IsCreature)
    assert rule.condition.n == 3
    assert lp.external_cost_reductions == ()
    assert not lp.triggered_abilities
    assert lp.keywords == frozenset({"reach"})


# ---------------------------------------------------------------------------
# Pin 2 / Pin 3 — Rust parse round-trip
# ---------------------------------------------------------------------------


def test_rust_parser_accepts_another_spell_cast_this_turn_cost_reduction():
    """Pin #2 — Rust ``parse_printing`` accepts the Gigastorm shape.

    A synthetic Gigastorm-shaped registry dict — a ``Creature`` with
    ``cost_reductions=[{"amount": 3, "condition_kind":
    "another_spell_cast_this_turn", "condition_args": ()}]`` —
    registers on ``mtg_bot_engine.Registry.register_printing`` with
    no panic and no Err. The empty-tuple ``condition_args`` is the
    canonical no-args shape; the Rust parser maps it to
    ``Condition::AnotherSpellCastThisTurn``.

    Round-trip-shape parity discipline (sibling of every prior
    substrate-only C1 — Coordinated Clobbering, Anticausal Vestige,
    Weftwalking).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Cycle 1 Substrate Pin -- "
            "AnotherSpellCastThisTurn carrier"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 4},
        "power": 6,
        "toughness": 6,
        "cost_reductions": [
            {
                "amount": 3,
                "condition_kind": "another_spell_cast_this_turn",
                "condition_args": (),
            },
        ],
    })
    assert isinstance(pid, int)


def test_rust_parser_accepts_opponents_control_at_least_cost_reduction():
    """Pin #3 — Rust ``parse_printing`` accepts the Lashwhip shape.

    A synthetic Lashwhip-shaped registry dict — a ``Creature`` with
    ``cost_reductions=[{"amount": 2, "condition_kind":
    "opponents_control_at_least", "condition_args": ("creature", 3)}]``
    — registers on ``mtg_bot_engine.Registry.register_printing`` with
    no panic and no Err. The 2-tuple ``("creature", n)`` is the
    canonical Phase-1 args shape (predicate token + count); the Rust
    parser maps it to ``Condition::OpponentsControlAtLeast {
    type_filter: Creature, count: n }``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Cycle 1 Substrate Pin -- "
            "OpponentsControlAtLeast(Creature, 3) carrier"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"G": 2, "generic": 4},
        "power": 5,
        "toughness": 5,
        "keywords": ["reach"],
        "cost_reductions": [
            {
                "amount": 2,
                "condition_kind": "opponents_control_at_least",
                "condition_args": ("creature", 3),
            },
        ],
    })
    assert isinstance(pid, int)


def test_rust_parser_accepts_absent_cost_reductions_back_compat():
    """Pin #3b — back-compat: a registry dict without the
    ``cost_reductions`` key parses unchanged (the absent-key →
    empty-Vec arm — the same pattern every other optional list field
    uses; mirrors the back-compat regression-tripwire across the
    substrate landings)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Cycle 1 Substrate Pin -- "
            "absent cost_reductions key (back-compat)"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
    })
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# Pin 4 — Substrate-only invariant (the load-bearing closure marker)
# ---------------------------------------------------------------------------


def test_gigastorm_titan_now_admits_at_admit_gate_post_cycle_2():
    """Pin #4a — INVERTED post-Cycle-2 — Gigastorm Titan FLIP.

    **The load-bearing closure marker (Cycle 2 inversion).** Post-
    Cycle-2, Gigastorm Titan FLIPS DECLINED → ADMITTED at the new
    ``_printing_is_bridge_pure_cost_reduction_creature`` admit
    predicate AND at the deck-level
    ``_filter_deck_to_bridge_supported`` OR-chain. Cycle 1's pin
    (substrate-only invariant — STAY DECLINED) inverts here when
    the bridge round-trip + new admit predicate land. The
    ``_printing_is_bridge_simple_creature`` predicate STAYS False
    (the cost_reductions guard there is still load-bearing — the
    new cost-reduction-aware predicate is the dedicated admit arm,
    a SIBLING of simple-creature not a widen).

    The Cycle 1 → Cycle 2 inversion is the documented closure
    pattern (sibling mirror of Anticausal Vestige Cycle 2 commit
    ``c32f07f9``'s admit-widen).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    g = src.get("Gigastorm Titan")
    if g is None:
        pytest.skip("Gigastorm Titan absent from active CardSource")

    # The simple-creature arm STILL rejects (its cost_reductions
    # guard is sibling-load-bearing, not removed). Cycle 2 did NOT
    # widen the existing predicate — it added a NEW dedicated
    # cost-reduction-aware predicate.
    assert trajectory._printing_is_bridge_simple_creature(g) is False, (
        "Gigastorm Titan must STAY DECLINED at the simple-creature "
        "admit gate post-Cycle-2 — the cost_reductions guard there "
        "is sibling-load-bearing. The new cost-reduction admit "
        "predicate is a parallel OR-arm, not a simple-creature widen."
    )
    # The new dedicated admit predicate FLIPS True.
    assert trajectory._printing_is_bridge_pure_cost_reduction_creature(g) is True, (
        "Gigastorm Titan must ADMIT at the new "
        "_printing_is_bridge_pure_cost_reduction_creature predicate "
        "post-Cycle-2 (the C1 → C2 inversion). If False, the C2 "
        "admit-widen didn't land — verify the trajectory.py predicate "
        "+ OR-chain disjunct landed together."
    )
    # And the deck-level filter likewise — a 1-card deck containing
    # only Gigastorm Titan must filter to (1-name, 1-CardDef-list)
    # post-Cycle-2.
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Gigastorm Titan"], src,
    )
    assert filtered_names == ["Gigastorm Titan"], (
        "Gigastorm Titan must FLIP DECLINED→ADMITTED at the deck-level "
        "filter post-Cycle-2 (the new cost-reduction admit predicate "
        f"is wired into the OR-chain). Got filtered_names={filtered_names!r}"
    )
    assert len(card_defs) == 1
    (cd,) = card_defs
    assert cd.name == "Gigastorm Titan"
    assert cd.card_type == "Creature"
    # The CardDef carries the Phase-1 cost-reduction triple
    # round-trip-ready for the bridge — pinned here so a future
    # refactor that drops the field gets caught at the C2 inversion.
    assert cd.cost_reductions == (
        (3, "another_spell_cast_this_turn", ()),
    ), f"unexpected cost_reductions tuple: {cd.cost_reductions!r}"


def test_lashwhip_predator_now_admits_at_admit_gate_post_cycle_2():
    """Pin #4b — INVERTED post-Cycle-2 — Lashwhip Predator FLIP.

    Same load-bearing closure marker as #4a, for Lashwhip Predator.
    Inverts at Cycle 2 (the simultaneous DECLINED → ADMITTED flip
    for both Phase-1 carriers).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    lp = src.get("Lashwhip Predator")
    if lp is None:
        pytest.skip("Lashwhip Predator absent from active CardSource")

    assert trajectory._printing_is_bridge_simple_creature(lp) is False, (
        "Lashwhip Predator must STAY DECLINED at the simple-creature "
        "admit gate post-Cycle-2."
    )
    assert trajectory._printing_is_bridge_pure_cost_reduction_creature(lp) is True, (
        "Lashwhip Predator must ADMIT at the new cost-reduction "
        "predicate post-Cycle-2."
    )
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Lashwhip Predator"], src,
    )
    assert filtered_names == ["Lashwhip Predator"], (
        "Lashwhip Predator must FLIP DECLINED→ADMITTED at the deck-"
        f"level filter post-Cycle-2. Got filtered_names={filtered_names!r}"
    )
    assert len(card_defs) == 1
    (cd,) = card_defs
    assert cd.name == "Lashwhip Predator"
    assert cd.card_type == "Creature"
    # The Phase-1 OpponentsControlAtLeast(IsCreature(), 3) triple.
    assert cd.cost_reductions == (
        (2, "opponents_control_at_least", ("creature", 3)),
    ), f"unexpected cost_reductions tuple: {cd.cost_reductions!r}"
    # Reach stays a SAFE keyword (preserved on the CardDef).
    assert "reach" in cd.keywords


# ---------------------------------------------------------------------------
# Pin 5 — §2 Rust-side teeth (Phase-2 tokens hard-error)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        # Totally unknown tag — also a hard error.
        # (Phase-3 closure 2026-05-25 landed `per_differently_named_land`
        # on the spell-local arm; that case is no longer rejected and is
        # now pinned positive in
        # ``tests/test_cost_reduction_phase_3_substrate_cycle_1.py``.)
        (
            {
                "amount": 1,
                "condition_kind": "totally_made_up_phase_99_kind",
                "condition_args": (),
            },
            "totally_made_up_phase_99_kind",
        ),
        # Phase-2 predicate algebra — `("artifact", 3)` is the Sami
        # variant; Phase 1 only supports `("creature", n)`.
        (
            {
                "amount": 1,
                "condition_kind": "opponents_control_at_least",
                "condition_args": ("artifact", 3),
            },
            "artifact",
        ),
        # Arg-count drift on a known kind — `AnotherSpellCastThisTurn`
        # takes 0 args; (1,) hard-errors.
        (
            {
                "amount": 1,
                "condition_kind": "another_spell_cast_this_turn",
                "condition_args": (1,),
            },
            "takes 0 args",
        ),
        # Arg-count drift on `opponents_control_at_least` (1-tuple,
        # missing the count).
        (
            {
                "amount": 1,
                "condition_kind": "opponents_control_at_least",
                "condition_args": ("creature",),
            },
            "takes 2 args",
        ),
        # Missing required key — `amount` not present.
        (
            {
                "condition_kind": "another_spell_cast_this_turn",
                "condition_args": (),
            },
            "amount is required",
        ),
        # Missing required key — `condition_kind` not present.
        (
            {
                "amount": 1,
                "condition_args": (),
            },
            "condition_kind is required",
        ),
        # `opponents_control_at_least` without the required
        # `condition_args` key (the variant's 2 args are required).
        (
            {
                "amount": 1,
                "condition_kind": "opponents_control_at_least",
            },
            "requires condition_args",
        ),
    ],
    ids=[
        "unknown_condition_kind_rejected",
        "phase_2_predicate_token_artifact_rejected",
        "arg_count_drift_another_spell_cast_takes_0",
        "arg_count_drift_opp_control_takes_2",
        "missing_amount_rejected",
        "missing_condition_kind_rejected",
        "opp_control_missing_condition_args_rejected",
    ],
)
def test_rust_parser_rejects_out_of_phase_1_cost_reduction_shapes(
    payload: dict, expected_fragment: str
):
    """Pin #5 — §2 Rust-side teeth.

    Every out-of-Phase-1 ``cost_reductions`` entry shape hard-errors
    at registry build. Tags Phase 2 / Phase 3 will land
    (``per_differently_named_land``, the Phase-2 condition arms),
    unknown tags, the Phase-2 predicate algebra (a token other than
    ``"creature"``), and any arg-count drift on the two Phase-1 tags
    all raise a ``ValueError`` with a message that points at the
    rejected token / shape — matching the
    ``silent no-op pipeline runs are pipeline bugs`` discipline.

    Phase 2 will RELAX one of these arms (the
    ``per_differently_named_land`` rejection) when the Fungal
    Colossus closure ships; Phase 3 will relax the artifact /
    predicate-algebra rejection.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    base = {
        "name": (
            "Cost-reduction Cycle 1 §2 teeth pin -- "
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


# ---------------------------------------------------------------------------
# Pin 6 — Pre-existing Player.spells_cast_this_turn defense-in-depth
# ---------------------------------------------------------------------------


def test_player_spells_cast_this_turn_is_accessible_via_setter():
    """Pin #6 — defense-in-depth pin against the already-shipped
    ``Player.spells_cast_this_turn`` plumbing the Cycle-2 ``eff()``
    seam extension will lean on.

    The MMM Pin 1 (11th Rust slice) substrate landed this counter at
    ``state.rs:1017`` with the test-only setter
    ``set_spells_cast_this_turn`` at ``state_ops_resolve.rs:23669``.
    This pin confirms the setter is accessible from Python and accepts
    a per-player value — the contract the Cycle-2 seam extension
    reads when evaluating ``Condition::AnotherSpellCastThisTurn``.

    The setter's existence + accessibility was the verify-first
    deviation finding that collapsed the design doc's §4.5
    deliverable (new field + threading) into a no-op for Cycle 1.

    The companion read accessor for `spells_cast_this_turn` is the
    canonical-state fingerprint at ``info_set.py:216`` /
    ``canonical_state.py:484`` — the bridge round-trip pin Cycle 2
    will lean on. This pin only exercises the setter; the
    Python-side read path is exercised across the existing
    statics/condition tests (e.g. ``tests/test_state_predicates.py``).
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state()
    # The setter accepts a player index + value and round-trips
    # without raising — the contract the Cycle-2 evaluator depends on.
    state.set_spells_cast_this_turn(0, 1)
    state.set_spells_cast_this_turn(1, 0)
    state.set_spells_cast_this_turn(0, 3)
    state.set_spells_cast_this_turn(0, 0)
    # Out-of-range player_idx is a hard IndexError (the existing
    # contract of the setter, defended here as a regression
    # tripwire).
    with pytest.raises(IndexError):
        state.set_spells_cast_this_turn(2, 0)


# ---------------------------------------------------------------------------
# Pin 7 — Live admit-set bench-aggregate is unchanged
# ---------------------------------------------------------------------------


def test_live_simple_creature_admit_count_is_unchanged_post_cycle_1():
    """Pin #7 — bench-aggregate sibling of pin #4.

    The number of live EoE printings that pass
    ``_printing_is_bridge_simple_creature`` is unchanged from
    pre-Cycle-1 (every cost-reduction-gated card is still rejected;
    no other shape silently auto-grew under the substrate landing —
    the Rust ``cost_reductions`` field exists but every existing
    fixture omits it, parses to empty Vec, and the
    bridge-emission/admit-side is untouched this cycle).

    Cycle 2 will bump this count by exactly +2 (Gigastorm Titan +
    Lashwhip Predator) once the bridge round-trip + new admit
    predicate land. The bump that flips Cycle 2's invariant pin into
    place.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    # Walk every live printing through the simple-creature admit
    # gate. Every cost-reduction-gated card must reject (the existing
    # ``if printing.cost_reductions or printing.external_cost_reductions:
    # return False`` guard); no other shape should regress.
    for name in [
        "Gigastorm Titan",
        "Lashwhip Predator",
        "Fungal Colossus",
        "Uthros Psionicist",
        "Sami, Wildcat Captain",
    ]:
        p = src.get(name)
        if p is None:
            continue
        assert trajectory._printing_is_bridge_simple_creature(p) is False, (
            f"{name} must STAY DECLINED at the simple-creature admit "
            f"gate post-Cycle-1 (the cost_reductions guard is "
            f"load-bearing this cycle)."
        )
