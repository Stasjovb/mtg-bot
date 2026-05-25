"""cost-reduction substrate Phase 3 — Cycle 2 (THE FLIP) pins.

**Lane.** ``feature/cost-reduction-phase-3-cycle-2-flip-p1`` (2026-05-25).

Cycle 2 of the cost-reduction substrate Phase 3 campaign per
``docs/COST_REDUCTION_SUBSTRATE_PHASE_3_DESIGN.md`` §5 + §7. C1
substrate landed at ``8525d18e``; this slice ships THE FLIP —
Fungal Colossus DECLINED → ADMITTED at the bridge admit gate.

**What Cycle 2 lands (the C1 → C2 closure):**

* **Bridge reverse-arm extension** (``cross_engine.py``'s
  ``_card_def_to_python_printing``): new ``per_differently_named_land``
  elif branch on the spell-local arm. Mirror of Phase-1's
  ``another_spell_cast_this_turn`` re-materialization arm; the
  ``condition_args`` MUST be empty (the §2 teeth — Rust's parse arm
  hard-errors on non-empty args).
* **Widened admit helper** (``trajectory.py``):
  ``_cost_reduction_rule_is_phase1`` renamed to
  ``_cost_reduction_rule_is_phase1_or_3`` (Option A per design doc
  §5.4) with the ``PerDifferentlyNamedLand`` isinstance arm
  appended. The outer
  :func:`_printing_is_bridge_pure_cost_reduction_creature` predicate
  flips True on Fungal Colossus.
* **Forward emit** in :func:`_printing_to_card_def`'s cost-reduction-
  aware CardDef arm: new ``PerDifferentlyNamedLand`` isinstance arm
  produces the wire triple ``(amount, "per_differently_named_land",
  ())``.
* **CardDef ``cost_reductions`` docstring** updated to list the new
  ``per_differently_named_land`` wire token (Phase 1 + Phase 3
  together carry exactly 3 spell-local ``condition_kind`` values).

**What Cycle 2 deliberately does NOT do** (per the campaign cadence
— these are Cycle 3 / Cycle 4 deliverables):

* No per-card real-EoE byte-equality probe — Cycle 3 ships
  ``tests/test_probe_fungal_colossus_real_eoe_cost_reduction.py``
  driving (a) full-cost path (0 lands), (b) reduced-cost path (4
  distinctly-named lands → ``{4}`` reduction), (c) multiplier-1
  path (4 lands sharing one name → ``{1}`` reduction). FLIPS
  Fungal Colossus covered_by_construction → PROBED.
* No Rust changes — C1 (commit ``8525d18e``) landed the full Rust
  substrate (``Condition::PerDifferentlyNamedLand`` variant +
  ``unique_land_names_count`` helper + ``apply_cost_reductions_rust``
  match arm + ``parse_printing`` arm + §2 teeth).
* The 9 Python sibling admit-guards ``if printing.cost_reductions or
  printing.external_cost_reductions: return False`` in
  ``trajectory.py`` STAY in place — the widened predicate is on the
  SAME named site, not a guard removal (defense-in-depth).

**What this module pins (Cycle 2 closure markers — design doc §7.2 +
§7.4 + drop-to-zero attribution).**

1. **Bridge round-trip — Fungal Colossus.** The CardDef triple
   ``(1, "per_differently_named_land", ())`` round-trips Python ↔
   Rust ↔ Python byte-equal. Python ``CardPrinting.cost_reductions``
   materializes as ``(CostReduction(amount=1,
   condition=PerDifferentlyNamedLand()),)`` — byte-equal to the live
   parser SoT (pinned by C1's #1).
2. **Forward-arm wire-token stability** (§7.2 pin 11). A Python-side
   ``CostReduction(amount=1, condition=PerDifferentlyNamedLand())``
   round-trips through ``_spec_card_to_printing_dict`` to the exact
   triple ``(1, "per_differently_named_land", ())``.
3. **Reverse-arm hard-error pin** (§7.2 pin 10 — the §2 teeth).
   ``_card_def_to_python_printing`` raises ``ValueError`` if a triple
   shaped ``(1, "per_differently_named_land", ("creature",))``
   (non-empty args on a unit-shape variant) is fed to the arm.
   Mirrors the Rust ``parse_printing`` hard-error.
4. **Admit set is EXACTLY 5** — ``{Gigastorm Titan, Lashwhip
   Predator, Uthros Psionicist, Sami, Wildcat Captain, Fungal
   Colossus}`` (subsystem-attribution pin; design doc §7.4 pin 13).
5. **Phase-1 + Phase-2 carriers still admit** (no regression) —
   defense-in-depth pin (design doc §7.3 6-pin shape last entry).
6. **Decline-set bench check.** Fungal Colossus filters through
   :func:`_filter_deck_to_bridge_supported` to a 1-card admit set
   (the C1 → C2 inversion at the bench level; design doc §7.4 pin 12
   — the load-bearing FLIP marker).
7. **Drop-to-zero subsystem-attribution pin** (design doc §7.4 pin
   14). After Phase-3-Cycle-2, no live EoE cost-reduction-gated card
   remains declined — the cost-reduction substrate retires from the
   single-gated rollup entirely.
8. **No-silent-auto-grow pin (bridge reverse arm — Phase-4 token)**
   (§7.4 pin 15). An accidentally-Phase-4 condition_kind on a
   synthetic CardDef (e.g. ``and_combinator``) raises ``ValueError``
   from the C2 reverse arm.
9. **No-other-Phase-3-carrier pin** (§7.4 pin 16). With the live EoE
   pool loaded, count printings whose ``cost_reductions`` contains
   EXACTLY a ``PerDifferentlyNamedLand`` rider; assert the count is
   EXACTLY 1 (Fungal Colossus).
10. **Sibling-guard defense-in-depth.** The 9 simple-* admit
    predicates with the ``if printing.cost_reductions or
    printing.external_cost_reductions: return False`` guard STILL
    reject all 5 carriers — the widened admit predicate is a
    PARALLEL on the same named site, NOT a guard removal.
"""

from __future__ import annotations

import importlib.util

import pytest


# Skip the whole module if the Rust extension isn't built.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Pin 1 — Bridge round-trip — Fungal Colossus (Python ↔ Rust ↔ Python)
# ---------------------------------------------------------------------------


def test_bridge_round_trip_fungal_colossus_byte_equal():
    """Pin #1 — Fungal Colossus bridge round-trip.

    The live parsed Fungal Colossus printing routes through:

      live printing
        → :func:`mtg_bot.parity.trajectory._printing_to_card_def`
        → CardDef.cost_reductions ==
          ``((1, "per_differently_named_land", ()),)``
        → :func:`_spec_card_to_printing_dict`
        → Rust registry dict with the canonical
          ``{"amount":1, "condition_kind":"per_differently_named_land",
           "condition_args":()}`` payload
        → ``mtg_bot_engine.Registry.register_printing`` (no panic /
          no Err)
        → :func:`_card_def_to_python_printing`
        → Python CardPrinting whose ``cost_reductions`` is byte-equal
          to the live-parsed
          ``(CostReduction(amount=1,
          condition=PerDifferentlyNamedLand()),)``.

    This is the Python ↔ Rust ↔ Python byte-equal closure the §5.3 +
    §7.2 spec demands.
    """
    import mtg_bot_engine
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    src = get_active_source().get_printings()
    p_orig = src.get("Fungal Colossus")
    if p_orig is None:
        pytest.skip("Fungal Colossus absent from active CardSource")

    cd = trajectory._printing_to_card_def(p_orig)
    assert cd.cost_reductions == (
        (1, "per_differently_named_land", ()),
    )
    # Externals stay empty — Fungal has spell-local only.
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

    # Rust registry accepts the round-tripped dict.
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(d)
    assert isinstance(pid, int)

    # Python reverse arm rematerializes a byte-equal CardPrinting.
    p_rt = _card_def_to_python_printing(cd)
    assert p_rt.cost_reductions == p_orig.cost_reductions
    # Defensive equality on the structural Condition itself.
    (rule_rt,) = p_rt.cost_reductions
    assert isinstance(rule_rt, CostReduction)
    assert rule_rt.amount == 1
    assert isinstance(rule_rt.condition, PerDifferentlyNamedLand)


# ---------------------------------------------------------------------------
# Pin 2 — Forward-arm wire-token stability (design doc §7.2 pin 11)
# ---------------------------------------------------------------------------


def test_forward_arm_wire_token_stability_per_differently_named_land():
    """Pin #2 — synthetic-CardDef forward emit.

    A Python-side ``CostReduction(amount=1,
    condition=PerDifferentlyNamedLand())`` re-materialized into a
    CardDef triple via the bridge forward arm produces EXACTLY the
    wire shape ``(1, "per_differently_named_land", ())`` — no
    field-order drift, no implicit-default leakage.

    Validates the inverse direction of the §5.3 spec (reverse-arm
    extension): the forward-emit arm in
    :func:`mtg_bot.parity.trajectory._printing_to_card_def` produces
    the same canonical triple shape the reverse arm consumes.
    """
    from mtg_bot.cards.base import CostReduction, CardPrinting, ManaCost
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    # Build a synthetic vanilla creature with the Phase-3 rider.
    p_synth = CardPrinting(
        name="Synthetic Phase-3 PerDifferentlyNamedLand carrier",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Creature",
        card_types=("Creature",),
        subtypes=(),
        supertypes=(),
        power=3,
        toughness=3,
        cost_reductions=(
            CostReduction(amount=1, condition=PerDifferentlyNamedLand()),
        ),
    )

    cd = trajectory._printing_to_card_def(p_synth)
    assert cd.cost_reductions == (
        (1, "per_differently_named_land", ()),
    ), f"forward emit drifted: {cd.cost_reductions!r}"
    # External arm stays empty.
    assert cd.external_cost_reductions == ()

    # Forward emit through registry dict.
    d = _spec_card_to_printing_dict(cd)
    assert d.get("cost_reductions") == [
        {
            "amount": 1,
            "condition_kind": "per_differently_named_land",
            "condition_args": (),
        },
    ], f"registry-dict drift: {d.get('cost_reductions')!r}"


# ---------------------------------------------------------------------------
# Pin 3 — Reverse-arm hard-error pin (§2 teeth — design doc §7.2 pin 10)
# ---------------------------------------------------------------------------


def test_per_differently_named_land_with_non_empty_args_raises_from_reverse_arm():
    """Pin #3 — §7.2 pin 10, bridge-side teeth.

    The Phase-3 reverse arm in
    :func:`mtg_bot.parity.cross_engine._card_def_to_python_printing`
    hard-errors when fed a ``per_differently_named_land`` triple with
    non-empty ``condition_args`` (the variant is unit-shape; takes 0
    args). No silent drop — matches the Rust ``parse_printing``
    hard-error from C1 substrate (commit ``8525d18e``).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    cd = CardDef(
        name="Phase-3 per_differently_named_land arg drift teeth probe",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(),
        power=1,
        toughness=1,
        cost_reductions=(
            (1, "per_differently_named_land", ("creature",)),
        ),
    )
    with pytest.raises(ValueError) as excinfo:
        _card_def_to_python_printing(cd)
    msg = str(excinfo.value)
    assert "per_differently_named_land" in msg or "takes 0 args" in msg, (
        f"Expected the rejection to mention the offending arg shape; "
        f"got: {msg!s}"
    )


# ---------------------------------------------------------------------------
# Pin 4 — Admit set is EXACTLY 5 carriers (design doc §7.4 pin 13)
# ---------------------------------------------------------------------------


def test_phase_3_cost_reduction_admit_set_is_exactly_five_carriers():
    """Pin #4 — admit set exhaustive post-Phase-3.

    The set of live EoE printings passing the widened
    :func:`_printing_is_bridge_pure_cost_reduction_creature` is
    EXACTLY ``{"Gigastorm Titan", "Lashwhip Predator", "Uthros
    Psionicist", "Sami, Wildcat Captain", "Fungal Colossus"}`` —
    the Phase-1 + Phase-2 + Phase-3 carriers. Subsystem-attribution
    pin (design doc §7.4 pin 13). Was 4 pre-Phase-3.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    admitted = sorted(
        name
        for name, printing in src.items()
        if trajectory._printing_is_bridge_pure_cost_reduction_creature(
            printing,
        )
    )
    assert admitted == [
        "Fungal Colossus",
        "Gigastorm Titan",
        "Lashwhip Predator",
        "Sami, Wildcat Captain",
        "Uthros Psionicist",
    ], (
        f"cost-reduction admit set drifted: {admitted!r} (expected "
        f"exactly the 5 Phase-1+2+3 carriers — Gigastorm Titan + "
        f"Lashwhip Predator + Uthros Psionicist + Sami, Wildcat "
        f"Captain + Fungal Colossus). If a new card joined, verify "
        f"it actually carries a Phase-1/3 cost_reductions shape OR a "
        f"Phase-2 ExternalCondition shape."
    )


# ---------------------------------------------------------------------------
# Pin 5 — Phase-1 + Phase-2 carriers still admit (no regression)
# ---------------------------------------------------------------------------


def test_phase_1_and_phase_2_carriers_still_admit_post_phase_3_cycle_2():
    """Pin #5 — Phase-1+2 carriers STILL admit (defense-in-depth).

    The Cycle-2 widening must not regress the Phase-1 + Phase-2
    admit set. Gigastorm Titan + Lashwhip Predator (Phase 1) +
    Uthros Psionicist + Sami, Wildcat Captain (Phase 2) all stay
    admitted through the SAME widened predicate.
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
            f"{name} (Phase-1/2 carrier) must STILL admit at the "
            f"cost-reduction admit predicate post-Phase-3-Cycle-2. "
            f"The Cycle-2 widening must not regress Phase-1/2."
        )


# ---------------------------------------------------------------------------
# Pin 6 — Decline-set bench check (design doc §7.4 pin 12 — the FLIP)
# ---------------------------------------------------------------------------


def test_fungal_colossus_filters_through_to_admitted_post_phase_3_cycle_2():
    """Pin #6 — Cycle-2 bench-level filter admits Fungal Colossus.

    Fungal Colossus filters through
    :func:`_filter_deck_to_bridge_supported` to a 1-card admit list
    post-Phase-3-Cycle-2 (the C1 → C2 inversion at the bench level).
    The Phase-3 card is now BRIDGE-SUPPORTED for cross-engine play.

    The load-bearing FLIP pin: failure of THIS pin means Phase 3
    didn't flip Fungal Colossus.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    if src.get("Fungal Colossus") is None:
        pytest.skip("Fungal Colossus absent from active CardSource")
    filtered_names, card_defs = (
        trajectory._filter_deck_to_bridge_supported(
            ["Fungal Colossus"], src,
        )
    )
    assert filtered_names == ["Fungal Colossus"], (
        "Fungal Colossus must admit through _filter_deck_to_bridge_"
        "supported post-Phase-3-Cycle-2 (the C1 → C2 FLIP). Got "
        f"filtered_names={filtered_names!r}"
    )
    assert len(card_defs) == 1
    (cd,) = card_defs
    assert cd.name == "Fungal Colossus"
    assert cd.card_type == "Creature"
    assert cd.cost_reductions == (
        (1, "per_differently_named_land", ()),
    )
    assert cd.external_cost_reductions == ()


# ---------------------------------------------------------------------------
# Pin 7 — Drop-to-zero subsystem-attribution pin (design doc §7.4 pin 14)
# ---------------------------------------------------------------------------


def test_no_live_eoe_cost_reduction_card_remains_declined_post_phase_3():
    """Pin #7 — drop-to-zero attribution pin.

    Post-Phase-3-Cycle-2, EVERY live EoE printing carrying any
    ``cost_reductions`` rider OR any ``external_cost_reductions``
    rider must EITHER admit at the widened
    :func:`_printing_is_bridge_pure_cost_reduction_creature`
    predicate OR be blocked by an unrelated rider (triggered_abilities,
    static_abilities, etc — the multi-gated path; design doc §3.1
    out-of-scope).

    The cost-reduction substrate's single-gated count drops from 1
    (Fungal Colossus, pre-Phase-3) to 0 (post-Phase-3-Cycle-2);
    BLOCKED 56 → 55. The substrate retires from the single-gated
    rollup entirely.

    This pin: for the 5 Phase-1/2/3 carriers (which we KNOW are bare
    creatures with only the cost-reduction rider — verified in C1's
    parser SoT pins + their respective probe modules), the admit
    predicate must flip True post-Cycle-2.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    # The 5 bare-cost-reduction carriers across Phase 1 + 2 + 3.
    bare_carriers = {
        "Gigastorm Titan",
        "Lashwhip Predator",
        "Uthros Psionicist",
        "Sami, Wildcat Captain",
        "Fungal Colossus",
    }
    admitted = {
        name
        for name, p in src.items()
        if trajectory._printing_is_bridge_pure_cost_reduction_creature(p)
    }
    # Every bare-cost-reduction carrier present in src must admit.
    for name in bare_carriers:
        if src.get(name) is None:
            continue
        assert name in admitted, (
            f"{name} must admit at the cost-reduction predicate post-"
            f"Phase-3-Cycle-2 — the drop-to-zero attribution pin "
            f"requires every bare-cost-reduction Phase-1/2/3 carrier "
            f"to flip admitted."
        )
    # And no card carrying ONLY a cost-reduction rider stays declined
    # after Cycle 2 (the "drop-to-zero" half).
    for name, p in src.items():
        # Identify printings whose ONLY non-vanilla rider is a cost-
        # reduction (no triggered, no activated, no static, no
        # spell_effect, no warp/kicker/impending, etc).
        if not (p.cost_reductions or p.external_cost_reductions):
            continue
        if (
            p.triggered_abilities
            or p.activated_abilities
            or p.static_abilities
            or p.spell_effect is not None
            or p.warp_cost is not None
            or p.kicker_cost is not None
            or p.impending_cost is not None
            or p.room_halves
            or p.loyalty is not None
            or p.station_threshold is not None
        ):
            continue  # multi-gated — out of substrate scope
        # Bare cost-reduction carrier — must admit.
        assert name in admitted, (
            f"{name} carries ONLY a cost-reduction rider but is "
            f"DECLINED post-Phase-3-Cycle-2 — the drop-to-zero "
            f"attribution pin requires every bare-cost-reduction "
            f"single-gated card to admit. Did a new EoE carrier "
            f"surface that needs a Phase-4 widen?"
        )


# ---------------------------------------------------------------------------
# Pin 8 — No-silent-auto-grow on a Phase-4 token (design doc §7.4 pin 15)
# ---------------------------------------------------------------------------


def test_phase_4_token_on_cost_reductions_raises_from_bridge_reverse_arm():
    """Pin #8 — §7.4 pin 15, bridge-side teeth on a future-phase token.

    The Cycle-2 reverse arm in
    :func:`mtg_bot.parity.cross_engine._card_def_to_python_printing`
    hard-errors when fed an unknown ``condition_kind`` on the spell-
    local arm (e.g. ``and_combinator`` — a Phase-4+ combinator that
    doesn't exist post-Phase-3). No silent drop.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    cd = CardDef(
        name="Phase-4 and_combinator teeth probe",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(),
        power=1,
        toughness=1,
        cost_reductions=(
            (1, "and_combinator", ()),
        ),
    )
    with pytest.raises(ValueError) as excinfo:
        _card_def_to_python_printing(cd)
    msg = str(excinfo.value)
    assert "and_combinator" in msg or "unsupported condition_kind" in msg, (
        f"Expected the rejection message to mention "
        f"'and_combinator' or 'unsupported condition_kind'; got: {msg!s}"
    )


# ---------------------------------------------------------------------------
# Pin 9 — No-other-Phase-3-carrier pin (design doc §7.4 pin 16)
# ---------------------------------------------------------------------------


def test_only_fungal_colossus_carries_per_differently_named_land():
    """Pin #9 — exactly 1 EoE carrier of PerDifferentlyNamedLand.

    Walk the live EoE pool; count printings whose ``cost_reductions``
    contains EXACTLY a ``PerDifferentlyNamedLand`` rider. The count
    MUST be exactly 1 (Fungal Colossus). The Phase-3-specific
    instance of the no-silent-auto-grow check — verifying no second
    EoE card secretly carries the new shape post-flip.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand

    src = get_active_source().get_printings()
    carriers = sorted(
        name
        for name, p in src.items()
        if any(
            isinstance(rule.condition, PerDifferentlyNamedLand)
            for rule in p.cost_reductions
        )
    )
    assert carriers == ["Fungal Colossus"], (
        f"Phase-3 PerDifferentlyNamedLand carrier set drifted: "
        f"{carriers!r} (expected exactly 1 — Fungal Colossus). "
        f"A new live-pool carrier surfaced; Phase 4 may need to widen "
        f"the substrate beyond the single-card slice this phase admits."
    )


# ---------------------------------------------------------------------------
# Pin 10 — Sibling-guard defense-in-depth (the 9 simple-* admit guards)
# ---------------------------------------------------------------------------


def test_phase_3_carrier_still_rejected_by_simple_creature_guard():
    """Pin #10 — sibling-guard defense-in-depth.

    The 9 sibling admit predicates with the ``if
    printing.cost_reductions or printing.external_cost_reductions:
    return False`` guard each STILL reject all 5 cost-reduction
    carriers (Phase-1 + Phase-2 + Phase-3). The widened admit
    predicate is a PARALLEL on the same named site, NOT a guard
    removal — every other admit predicate stays defended.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    for name in [
        "Gigastorm Titan",
        "Lashwhip Predator",
        "Uthros Psionicist",
        "Sami, Wildcat Captain",
        "Fungal Colossus",
    ]:
        p = src.get(name)
        if p is None:
            continue
        assert trajectory._printing_is_bridge_simple_creature(p) is False, (
            f"{name} must STAY REJECTED at the simple-creature admit "
            f"gate post-Phase-3-Cycle-2 — the cost_reductions/"
            f"external_cost_reductions guard there is sibling-load-"
            f"bearing (the widened cost-reduction-aware predicate is "
            f"a PARALLEL on the same named site, NOT a simple-creature "
            f"widen)."
        )


# ---------------------------------------------------------------------------
# Pin 11 — The widened helper directly admits Fungal's rule
# ---------------------------------------------------------------------------


def test_cost_reduction_rule_is_phase1_or_3_admits_per_differently_named_land():
    """Pin #11 — directly exercises the widened rule helper.

    The renamed + extended
    :func:`mtg_bot.parity.trajectory._cost_reduction_rule_is_phase1_or_3`
    helper returns True for the canonical Fungal Colossus rule shape
    ``CostReduction(amount=1, condition=PerDifferentlyNamedLand())``
    AND continues to return True on the Phase-1 shapes (Gigastorm,
    Lashwhip). The §2 teeth: it returns False on any other
    ``Condition`` subclass (a future Phase-4+ combinator like
    ``AndCondition`` is rejected via the final ``return False``
    fallthrough).
    """
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.effects.conditions import (
        AnotherSpellCastThisTurn,
        OpponentsControlAtLeast,
        PerDifferentlyNamedLand,
    )
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.parity.trajectory import _cost_reduction_rule_is_phase1_or_3

    # Phase 1 — AnotherSpellCastThisTurn.
    assert _cost_reduction_rule_is_phase1_or_3(
        CostReduction(amount=3, condition=AnotherSpellCastThisTurn()),
    ) is True
    # Phase 1 — OpponentsControlAtLeast(IsCreature(), 3).
    assert _cost_reduction_rule_is_phase1_or_3(
        CostReduction(
            amount=2,
            condition=OpponentsControlAtLeast(IsCreature(), 3),
        ),
    ) is True
    # Phase 3 — PerDifferentlyNamedLand (NEW).
    assert _cost_reduction_rule_is_phase1_or_3(
        CostReduction(amount=1, condition=PerDifferentlyNamedLand()),
    ) is True

    # §2 teeth — a non-Phase-1/3 Condition subclass returns False.
    class _FakePhase4Condition:
        pass

    class _FakeRule:
        condition = _FakePhase4Condition()

    assert _cost_reduction_rule_is_phase1_or_3(_FakeRule()) is False
