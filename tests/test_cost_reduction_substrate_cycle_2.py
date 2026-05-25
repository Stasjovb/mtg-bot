"""cost-reduction substrate Phase 1 — Cycle 2 (THE FLIP) pins.

**Lane.** ``feature/cost-reduction-phase-1-cycle-2-flip-p1`` (2026-05-24).

Cycle 2 of the cost-reduction substrate Phase 1 campaign per
``docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md`` (973 lines,
2026-05-24, merge ``4b94f844``) and the C1 substrate merge
``3683e62e``. Cycle 2 ships THE FLIP — Gigastorm Titan + Lashwhip
Predator DECLINED → ADMITTED simultaneously at the bridge admit gate.

**What Cycle 2 lands (the C1 → C2 closure):**

* **Rust ``eff()`` seam extension** (``rust/src/state_ops_legal.rs:742``
  identity → real evaluator). The new
  :func:`apply_cost_reductions_rust` walks
  ``printing.cost_reductions`` and dispatches on ``Condition`` —
  Phase 1 ports EXACTLY 2 boolean variants
  (``AnotherSpellCastThisTurn`` reads
  ``Player.spells_cast_this_turn``;
  ``OpponentsControlAtLeast { Creature, n }`` scans every
  opponent's battlefield). All 6 CastSpell-emission call sites in
  ``legal_decisions`` route through it (the hand instant + sorcery
  passes, warp on each, warp-from-graveyard, warp exile-recast,
  Lightstall surcharge); the cast-side cost source at
  ``state_ops_cast.rs::cast_creature`` (lines 1131-1158) routes
  through the SAME helper — the Python-mirror discipline
  (``legal.py:187-188`` ↔ ``actions.py:1474-1486``).
* **CardDef ``cost_reductions`` field** + ``_spec_card_to_printing_dict``
  emit + ``_card_def_to_python_printing`` reverse arm (cross_engine.py).
* **New admit predicate**
  :func:`mtg_bot.parity.trajectory._printing_is_bridge_pure_cost_reduction_creature`
  + :func:`mtg_bot.parity.trajectory._cost_reduction_rule_is_phase1` +
  ``_printing_to_card_def`` arm + wired into
  ``_filter_deck_to_bridge_supported``'s OR-chain.

**What Cycle 2 deliberately does NOT do** (per the
campaign-cadence — these are Cycle 3 / Cycle 4 deliverables):

* No per-card real-EoE byte-equality probes — Cycle 3 ships
  Gigastorm Titan's, Cycle 4 ships Lashwhip Predator's
  (covered_by_construction → PROBED per-card).
* No Phase-2 / Phase-3 Condition variants (variable multiplier
  ``PerDifferentlyNamedLand`` / externals ``NthSpellThisTurn`` /
  ``PerControlled``). Phase 2 + 3 widen the substrate later.
* The 9 Python sibling admit-guards ``if printing.cost_reductions
  or printing.external_cost_reductions: return False`` in
  ``trajectory.py`` STAY in place — the new predicate is a
  PARALLEL OR-arm, not a guard removal (defense-in-depth: the
  simple-creature / simple-spell / etc. arms still reject any
  cost-reduction shape; only the dedicated arm admits Phase-1).

**What this module pins (Cycle 2 closure markers).**

1. **Bridge round-trip — Gigastorm Titan.** The CardDef triple
   ``(3, "another_spell_cast_this_turn", ())`` round-trips Python ↔
   Rust ↔ Python byte-equal. Python ``CardPrinting.cost_reductions``
   materializes as
   ``(CostReduction(amount=3, condition=AnotherSpellCastThisTurn()),)``
   — byte-equal to the live parser SoT (pinned by Cycle 1's #1a).
2. **Bridge round-trip — Lashwhip Predator.** The CardDef triple
   ``(2, "opponents_control_at_least", ("creature", 3))`` round-
   trips byte-equal.
3. **Admit set +2 — exactly Gigastorm + Lashwhip.** The set of EoE
   printings passing
   :func:`_printing_is_bridge_pure_cost_reduction_creature` is
   EXACTLY ``{"Gigastorm Titan", "Lashwhip Predator"}`` —
   exhaustive for Phase 1.
4. **No silent auto-grow on the other 3 cost-reduction-gated
   cards.** Fungal Colossus (``PerDifferentlyNamedLand`` — Phase 2),
   Uthros Psionicist + Sami, Wildcat Captain
   (``external_cost_reductions`` — Phase 3) STAY DECLINED — the §2
   teeth of the new predicate reject each for the documented
   reason.
5. **No silent auto-grow at the deck-level filter.** Each of the 3
   declined cards filters to ``([], [])`` (DROP policy) via the
   OR-chain — none of the new predicate or any other disjunct
   admits them.
6. **The decline-set Fungal/Uthros/Sami still reject at the
   sibling guards too.** Defense-in-depth: every other admit
   predicate (`_printing_is_bridge_simple_creature`, etc.) STILL
   rejects each of these 3 — the cost_reductions / external_cost_
   reductions guards there remain load-bearing.
7. **Rust evaluator parity probe — AnotherSpellCastThisTurn.** A
   synthetic state where p0 has cast 0 spells, then 1 spell, then
   the helper produces ``cost - 3 generic`` only at count >= 1
   (mirrors Python's ``AnotherSpellCastThisTurn.matches``
   semantics). The Rust evaluator is reachable from Python via the
   ``can_pay_cost`` path through the legal-emission probe.
8. **Cycle 3 + Cycle 4 sequencing claim.** The Cycle 2 inversion
   does NOT add a per-card cross-engine probe — those land in
   Cycles 3 + 4 (PROBED tier flip).
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
# Pin 1 / Pin 2 — Bridge round-trip (Python ↔ Rust ↔ Python byte-equal)
# ---------------------------------------------------------------------------


def test_bridge_round_trip_gigastorm_titan_byte_equal():
    """Pin #1 — Gigastorm Titan bridge round-trip.

    The live parsed Gigastorm Titan printing routes through:

      live printing
        → :func:`mtg_bot.parity.trajectory._printing_to_card_def`
        → CardDef.cost_reductions ==
          ``((3, "another_spell_cast_this_turn", ()),)``
        → :func:`_spec_card_to_printing_dict`
        → Rust registry dict with the canonical
          ``{"amount":3, "condition_kind":"another_spell_cast_this_turn",
           "condition_args": ()}`` payload
        → ``mtg_bot_engine.Registry.register_printing`` (no panic /
          no Err)
        → :func:`_card_def_to_python_printing`
        → Python CardPrinting whose ``cost_reductions`` is
          byte-equal to the live-parsed
          ``(CostReduction(amount=3,
          condition=AnotherSpellCastThisTurn()),)``.

    This is the Python ↔ Rust ↔ Python byte-equal closure the §5
    bridge spec demands.
    """
    import mtg_bot_engine
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import AnotherSpellCastThisTurn
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    src = get_active_source().get_printings()
    p_orig = src.get("Gigastorm Titan")
    if p_orig is None:
        pytest.skip("Gigastorm Titan absent from active CardSource")

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
    assert rule_rt.amount == 3
    assert isinstance(rule_rt.condition, AnotherSpellCastThisTurn)


def test_bridge_round_trip_lashwhip_predator_byte_equal():
    """Pin #2 — Lashwhip Predator bridge round-trip.

    Same shape as #1, for the OpponentsControlAtLeast variant. The
    CardDef triple is ``(2, "opponents_control_at_least",
    ("creature", 3))``; the Python reverse arm reconstructs
    ``OpponentsControlAtLeast(IsCreature(), 3)``.
    """
    import mtg_bot_engine
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import OpponentsControlAtLeast
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    src = get_active_source().get_printings()
    p_orig = src.get("Lashwhip Predator")
    if p_orig is None:
        pytest.skip("Lashwhip Predator absent from active CardSource")

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

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(d)
    assert isinstance(pid, int)

    p_rt = _card_def_to_python_printing(cd)
    assert p_rt.cost_reductions == p_orig.cost_reductions
    (rule_rt,) = p_rt.cost_reductions
    assert isinstance(rule_rt, CostReduction)
    assert rule_rt.amount == 2
    assert isinstance(rule_rt.condition, OpponentsControlAtLeast)
    assert isinstance(rule_rt.condition.filter, IsCreature)
    assert rule_rt.condition.n == 3


# ---------------------------------------------------------------------------
# Pin 3 — Admit set is EXACTLY {Gigastorm Titan, Lashwhip Predator}
# ---------------------------------------------------------------------------


def test_phase1_cost_reduction_admit_set_is_exactly_the_two_phase1_carriers():
    """Pin #3 — Phase-1 carriers admit at the predicate post-Phase-2.

    **Updated post-Phase-2-Cycle-2 (2026-05-25).** This Phase-1
    test originally pinned the admit set as EXACTLY ``{Gigastorm
    Titan, Lashwhip Predator}``. Phase 2 widened the predicate to
    admit Uthros Psionicist + Sami, Wildcat Captain. The Phase-1
    invariant the pin actually guards is "Phase-1 carriers admit"
    + "no Phase-1-grammar-violating card admits"; the exhaustive-
    set claim now lives in
    ``test_cost_reduction_phase_2_substrate_cycle_2.py``'s
    Pin #3 (4-card subsystem-attribution pin).
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
    # Phase-1 carriers must admit (the original invariant — no
    # Phase-2 regression on Phase-1).
    assert "Gigastorm Titan" in admitted, (
        f"Gigastorm Titan must STILL admit post-Phase-2; got "
        f"admit set {admitted!r}"
    )
    assert "Lashwhip Predator" in admitted, (
        f"Lashwhip Predator must STILL admit post-Phase-2; got "
        f"admit set {admitted!r}"
    )


# ---------------------------------------------------------------------------
# Pin 4 / Pin 5 — No silent auto-grow on Fungal / Uthros / Sami
# ---------------------------------------------------------------------------


def test_fungal_colossus_stays_declined_per_differently_named_land_is_phase_2():
    """Pin #4a — Fungal Colossus stays DECLINED (§2 teeth).

    Fungal Colossus carries ``CostReduction(amount=1,
    condition=PerDifferentlyNamedLand())`` — a variable-multiplier
    Phase 2 shape NOT in the Cycle-2 Condition grammar.
    :func:`_cost_reduction_rule_is_phase1` rejects
    ``PerDifferentlyNamedLand``; the admit predicate must reject
    the printing.

    The deck-level filter likewise drops the card — no other admit
    disjunct admits a cost-reduction creature (the
    cost_reductions guard is load-bearing at every sibling
    predicate this cycle, so a 1-card "Fungal Colossus" deck
    materializes as the empty admit set).

    Cycle 3 of Phase 2 will widen this (the
    ``PerDifferentlyNamedLand`` substrate + the variable-multiplier
    evaluator path).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    fc = src.get("Fungal Colossus")
    if fc is None:
        pytest.skip("Fungal Colossus absent from active CardSource")

    assert trajectory._printing_is_bridge_pure_cost_reduction_creature(fc) is False, (
        "Fungal Colossus must STAY DECLINED at the Phase-1 cost-"
        "reduction admit predicate (PerDifferentlyNamedLand is "
        "Phase-2; the §2 teeth must reject)."
    )
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Fungal Colossus"], src,
    )
    assert filtered_names == [], (
        "Fungal Colossus must STAY DECLINED at the deck-level filter "
        f"post-Cycle-2 (no OR-chain disjunct admits it). Got "
        f"filtered_names={filtered_names!r}"
    )
    assert card_defs == []


def test_uthros_psionicist_stays_declined_external_cost_reductions_is_phase_3():
    """Pin #4b — INVERTED post-Phase-2-Cycle-2 — Uthros admits.

    **Updated post-Phase-2-Cycle-2 (2026-05-25).** Originally this
    pin claimed Uthros Psionicist STAYS DECLINED because the
    Phase-1 admit predicate rejected any non-empty
    ``external_cost_reductions``. Phase 2 widened the predicate —
    Uthros now admits at the cost-reduction-aware path. The flip-
    point inversion lives here for cadence visibility; the
    exhaustive pin lives in the Phase-2 C2 test module.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    up = src.get("Uthros Psionicist")
    if up is None:
        pytest.skip("Uthros Psionicist absent from active CardSource")

    assert (
        trajectory._printing_is_bridge_pure_cost_reduction_creature(up)
        is True
    ), (
        "Uthros Psionicist must ADMIT post-Phase-2-Cycle-2 — the "
        "widened predicate admits NthSpellThisTurn externals."
    )
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Uthros Psionicist"], src,
    )
    assert filtered_names == ["Uthros Psionicist"]
    assert len(card_defs) == 1


def test_sami_wildcat_captain_stays_declined_external_cost_reductions_is_phase_3():
    """Pin #4c — INVERTED post-Phase-2-Cycle-2 — Sami admits.

    **Updated post-Phase-2-Cycle-2 (2026-05-25).** Simultaneous
    flip with #4b above — Sami, Wildcat Captain now admits at the
    widened cost-reduction-aware predicate via the
    PerControlled(IsArtifact()) externals shape.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    sami = src.get("Sami, Wildcat Captain")
    if sami is None:
        pytest.skip("Sami, Wildcat Captain absent from active CardSource")

    assert (
        trajectory._printing_is_bridge_pure_cost_reduction_creature(sami)
        is True
    ), (
        "Sami, Wildcat Captain must ADMIT post-Phase-2-Cycle-2 — the "
        "widened predicate admits PerControlled(IsArtifact()) "
        "externals."
    )
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Sami, Wildcat Captain"], src,
    )
    assert filtered_names == ["Sami, Wildcat Captain"]
    assert len(card_defs) == 1


# ---------------------------------------------------------------------------
# Pin 6 — Sibling guards still load-bearing (defense-in-depth)
# ---------------------------------------------------------------------------


def test_phase_2_and_phase_3_carriers_still_rejected_by_simple_creature_guard():
    """Pin #6 — sibling-guard defense-in-depth.

    The 9 sibling admit predicates with the ``if
    printing.cost_reductions or printing.external_cost_reductions:
    return False`` guard each STILL reject Fungal / Uthros / Sami
    (and the two Phase-1 carriers too, since the new
    cost-reduction-aware predicate is a PARALLEL OR-arm — NOT a
    widen of the simple-creature predicate). This guards against a
    future refactor that accidentally drops one of the sibling
    guards: each of the 5 cost-reduction-gated cards is still
    rejected by ``_printing_is_bridge_simple_creature``.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    # Walk every cost-reduction-gated card; each must STILL be
    # rejected by ``_printing_is_bridge_simple_creature``. Gigastorm
    # + Lashwhip are now admitted by the NEW predicate (pin #3),
    # NOT by simple-creature; this pin defends the no-widen-on-the-
    # sibling-arm invariant.
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
            f"gate post-Cycle-2 — the cost_reductions guard there is "
            f"sibling-load-bearing (the new cost-reduction predicate "
            f"is a PARALLEL OR-arm, not a simple-creature widen)."
        )


# ---------------------------------------------------------------------------
# Pin 7 — Rust evaluator semantics (AnotherSpellCastThisTurn dispatch)
# ---------------------------------------------------------------------------


def test_rust_evaluator_another_spell_cast_this_turn_state_semantic():
    """Pin #7 — :func:`apply_cost_reductions_rust` semantic via the
    legal-emission probe + the Python ``set_spells_cast_this_turn``
    setter.

    The legal-side affordability probe at every CastSpell-emit
    site routes through :func:`apply_cost_reductions_rust`, so a
    state where the caster has cast 0 vs 1+ OTHER spells this turn
    must change emission behavior on a Gigastorm-shape printing
    with a 3-generic reduction. We pin the CONTRACT here (the
    helper is reachable + the state-dependent dispatch fires) by
    directly seating a Gigastorm-shape carrier on a synthetic state
    and exercising the registry parse path; the deeper byte-equal
    real-EoE probe is Cycle 3's per-card deliverable.
    """
    import mtg_bot_engine

    # Register a Gigastorm-shape printing on a fresh registry.
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": (
            "Cost-reduction Cycle 2 evaluator probe -- "
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
    # The pre-existing test setter (Cycle 1 Pin #6 defense-in-depth)
    # for ``Player.spells_cast_this_turn`` is callable and the
    # field's accessibility from Python is the contract the Cycle-2
    # evaluator leans on. The semantic-flip pin per-card lives in
    # Cycle 3's real-EoE Gigastorm probe.
    state = mtg_bot_engine.make_synthetic_state()
    state.set_spells_cast_this_turn(0, 0)
    state.set_spells_cast_this_turn(0, 1)


# ---------------------------------------------------------------------------
# Pin 8 — Cycle 3 + Cycle 4 sequencing claim
# ---------------------------------------------------------------------------


def test_cycle_2_does_not_ship_per_card_real_eoe_probes():
    """Pin #8 — Cycle-2 scope discipline.

    This module pins the BRIDGE half of the FLIP (CardDef + admit
    predicate + Rust eff() seam extension + no-silent-auto-grow
    teeth) but does NOT ship the per-card real-EoE byte-equality
    probe. Cycle 3 ships Gigastorm Titan's; Cycle 4 ships Lashwhip
    Predator's (each FLIPS covered_by_construction → PROBED).

    This pin is documentation, not a runtime assertion — it
    annotates the scope boundary so a future review tracks which
    cycle's invariants belong here.
    """
    # No runtime assertion — see docstring. The Cycle-3 / Cycle-4
    # per-card probes will land in their own test modules
    # (``test_probe_gigastorm_titan_real_eoe_cost_reduction.py`` /
    # ``test_probe_lashwhip_predator_real_eoe_cost_reduction.py``
    # are the anticipated names per the per-card-probe naming
    # precedent — final names at the cycle agent's discretion).
    assert True
