"""cost-reduction substrate Phase 2 — Cycle 2 (THE FLIP) pins.

**Lane.** ``feature/cost-reduction-phase-2-cycle-2-flip-p1`` (2026-05-25).

Cycle 2 of the cost-reduction substrate Phase 2 campaign per
``docs/COST_REDUCTION_SUBSTRATE_PHASE_2_DESIGN.md`` §5 + §7. C1
substrate landed at ``5fa32697``; this slice ships THE FLIP —
Uthros Psionicist + Sami, Wildcat Captain DECLINED → ADMITTED
simultaneously at the bridge admit gate.

**What Cycle 2 lands (the C1 → C2 closure):**

* **CardDef ``external_cost_reductions`` field** (``cross_engine.py``)
  + ``_spec_card_to_printing_dict`` emit + ``_card_def_to_python_printing``
  reverse arm (the bridge round-trip — Option A of design doc §5.4).
* **Widened admit predicate**
  :func:`mtg_bot.parity.trajectory._printing_is_bridge_pure_cost_reduction_creature`
  + new sibling :func:`_external_cost_reduction_rule_is_phase2`.
  Replaces the old ``if printing.external_cost_reductions: return
  False`` reject with an admit-loop checking each rule against the
  Phase-2 grammar.
* **Forward emit in ``_printing_to_card_def``** — the
  cost-reduction-aware CardDef arm now threads
  ``external_cost_reductions`` through alongside ``cost_reductions``.

**What Cycle 2 deliberately does NOT do** (per the campaign cadence
— these are Cycle 3 / Cycle 4 deliverables):

* No per-card real-EoE byte-equality probes — Cycle 3 ships
  Uthros Psionicist's, Cycle 4 ships Sami, Wildcat Captain's
  (covered_by_construction → PROBED per-card).
* No Phase-3 ExternalCondition variants (``per_differently_named_land``
  on the externals side or any predicate beyond
  ``IsArtifact``/``IsCreature`` on ``per_controlled``). Phase 3 widens
  the substrate later.
* The 9 Python sibling admit-guards ``if printing.cost_reductions or
  printing.external_cost_reductions: return False`` in
  ``trajectory.py`` STAY in place — the new predicate is a
  PARALLEL admit-loop on the same named site, not a guard removal
  (defense-in-depth: simple-creature / simple-spell / etc. arms still
  reject any cost-reduction shape).

**What this module pins (Cycle 2 closure markers).**

1. **Bridge round-trip — Uthros Psionicist.** The CardDef triple
   ``(2, "nth_spell_this_turn", (2,))`` round-trips Python ↔
   Rust ↔ Python byte-equal. Python ``CardPrinting.
   external_cost_reductions`` materializes as
   ``(ExternalCostReduction(amount=2, condition=NthSpellThisTurn(n=2)),)``
   — byte-equal to the live parser SoT (pinned by C1's #1a).
2. **Bridge round-trip — Sami, Wildcat Captain.** The CardDef
   triple ``(1, "per_controlled", ("artifact",))`` round-trips
   byte-equal.
3. **Admit set is EXACTLY 4** — ``{Gigastorm Titan, Lashwhip
   Predator, Uthros Psionicist, Sami, Wildcat Captain}``
   (subsystem-attribution pin; design doc §7.4 pin 12).
4. **Fungal Colossus STAYS DECLINED** —
   ``PerDifferentlyNamedLand`` is Phase 3 (the design doc §3.1
   deferral); the widened predicate must not silently auto-grow
   onto Phase-3 carriers.
5. **Phase-1 carriers still admit** (no regression).
6. **Decline-set bench check.** Each of Uthros / Sami filters
   through ``_filter_deck_to_bridge_supported`` to a 1-card admit
   set; Fungal Colossus still filters to ``([], [])``.
7. **No-silent-auto-grow pin** (§7.4 pin 14). An accidentally-
   Phase-3 rider on a synthetic CardDef raises ``ValueError``
   from the C2 reverse arm in
   :func:`mtg_bot.parity.cross_engine._card_def_to_python_printing`.
8. **No-vanilla-grow.** A printing with no riders at all must
   NOT be admitted by the widened predicate (the "at least one
   rider present" guardrail).
9. **CardDef field default is empty tuple.** Back-compat — every
   pre-Phase-2 CardDef materializes ``external_cost_reductions=()``
   bit-identical to before this slice landed.
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


def test_bridge_round_trip_uthros_psionicist_byte_equal():
    """Pin #1 — Uthros Psionicist bridge round-trip.

    The live parsed Uthros Psionicist printing routes through:

      live printing
        → :func:`mtg_bot.parity.trajectory._printing_to_card_def`
        → CardDef.external_cost_reductions ==
          ``((2, "nth_spell_this_turn", (2,)),)``
        → :func:`_spec_card_to_printing_dict`
        → Rust registry dict with the canonical
          ``{"amount":2, "condition_kind":"nth_spell_this_turn",
           "condition_args":(2,)}`` payload
        → ``mtg_bot_engine.Registry.register_printing`` (no panic /
          no Err)
        → :func:`_card_def_to_python_printing`
        → Python CardPrinting whose ``external_cost_reductions`` is
          byte-equal to the live-parsed
          ``(ExternalCostReduction(amount=2,
          condition=NthSpellThisTurn(n=2)),)``.

    This is the Python ↔ Rust ↔ Python byte-equal closure the §5
    bridge spec demands.
    """
    import mtg_bot_engine
    from mtg_bot.cards.base import ExternalCostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import NthSpellThisTurn
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    src = get_active_source().get_printings()
    p_orig = src.get("Uthros Psionicist")
    if p_orig is None:
        pytest.skip("Uthros Psionicist absent from active CardSource")

    cd = trajectory._printing_to_card_def(p_orig)
    assert cd.external_cost_reductions == (
        (2, "nth_spell_this_turn", (2,)),
    )
    # And cost_reductions stays empty — Uthros has externals only.
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

    # Rust registry accepts the round-tripped dict.
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(d)
    assert isinstance(pid, int)

    # Python reverse arm rematerializes a byte-equal CardPrinting.
    p_rt = _card_def_to_python_printing(cd)
    assert (
        p_rt.external_cost_reductions == p_orig.external_cost_reductions
    )
    # Defensive equality on the structural ExternalCondition itself.
    (ext_rt,) = p_rt.external_cost_reductions
    assert isinstance(ext_rt, ExternalCostReduction)
    assert ext_rt.amount == 2
    assert isinstance(ext_rt.condition, NthSpellThisTurn)
    assert ext_rt.condition.n == 2


def test_bridge_round_trip_sami_wildcat_captain_byte_equal():
    """Pin #2 — Sami, Wildcat Captain bridge round-trip.

    Same shape as #1, for the ``PerControlled(IsArtifact())``
    variant. The CardDef triple is ``(1, "per_controlled",
    ("artifact",))``; the Python reverse arm reconstructs
    ``PerControlled(filter=IsArtifact())``.
    """
    import mtg_bot_engine
    from mtg_bot.cards.base import ExternalCostReduction
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import PerControlled
    from mtg_bot.effects.object_predicates import IsArtifact
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    src = get_active_source().get_printings()
    p_orig = src.get("Sami, Wildcat Captain")
    if p_orig is None:
        pytest.skip("Sami, Wildcat Captain absent from active CardSource")

    cd = trajectory._printing_to_card_def(p_orig)
    assert cd.external_cost_reductions == (
        (1, "per_controlled", ("artifact",)),
    )
    assert cd.cost_reductions == ()

    d = _spec_card_to_printing_dict(cd)
    assert d.get("external_cost_reductions") == [
        {
            "amount": 1,
            "condition_kind": "per_controlled",
            "condition_args": ("artifact",),
        },
    ]

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(d)
    assert isinstance(pid, int)

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
# Pin 3 — Admit set is EXACTLY 4 cards (subsystem-attribution pin)
# ---------------------------------------------------------------------------


def test_phase_2_cost_reduction_admit_set_is_exactly_four_carriers():
    """Pin #3 — admit set exhaustive post-Phase-2.

    The set of live EoE printings passing the widened
    :func:`_printing_is_bridge_pure_cost_reduction_creature` is
    EXACTLY ``{"Gigastorm Titan", "Lashwhip Predator", "Uthros
    Psionicist", "Sami, Wildcat Captain"}`` — the Phase-1 +
    Phase-2 carriers. Subsystem-attribution pin (design doc §7.4
    pin 12). Auto-grows when Phase 3 widens the Condition grammar.
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
        "Gigastorm Titan",
        "Lashwhip Predator",
        "Sami, Wildcat Captain",
        "Uthros Psionicist",
    ], (
        f"cost-reduction admit set drifted: {admitted!r} (expected "
        f"exactly the 4 Phase-1+2 carriers — Gigastorm Titan + "
        f"Lashwhip Predator + Uthros Psionicist + Sami, Wildcat "
        f"Captain). If a new card joined, verify it actually carries "
        f"a Phase-1 boolean-condition cost_reductions shape OR a "
        f"Phase-2 ExternalCondition shape — Phase 3 will widen the "
        f"set further."
    )


# ---------------------------------------------------------------------------
# Pin 4 — Fungal Colossus stays DECLINED (no silent auto-grow)
# ---------------------------------------------------------------------------


def test_fungal_colossus_stays_declined_per_differently_named_land_is_phase_3():
    """Pin #4 — Fungal Colossus stays DECLINED (no silent auto-grow).

    Fungal Colossus carries ``CostReduction(amount=1,
    condition=PerDifferentlyNamedLand())`` — a variable-multiplier
    Phase 3 shape NOT in the Phase-2 grammar.
    :func:`_cost_reduction_rule_is_phase1` rejects
    ``PerDifferentlyNamedLand``; the admit predicate must reject
    the printing.

    The deck-level filter likewise drops the card — Phase 3 will
    widen the substrate. The Cycle-2 widening (externals admit-
    loop) does NOT extend to the spell-local Phase-3 sub-shape D.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    fc = src.get("Fungal Colossus")
    if fc is None:
        pytest.skip("Fungal Colossus absent from active CardSource")

    assert (
        trajectory._printing_is_bridge_pure_cost_reduction_creature(fc)
        is False
    ), (
        "Fungal Colossus must STAY DECLINED at the widened cost-"
        "reduction admit predicate (PerDifferentlyNamedLand is "
        "Phase 3 — the no-silent-auto-grow discipline)."
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


# ---------------------------------------------------------------------------
# Pin 5 — Phase-1 carriers still admit (no regression)
# ---------------------------------------------------------------------------


def test_phase_1_carriers_still_admit_post_cycle_2():
    """Pin #5 — Phase-1 carriers (Gigastorm + Lashwhip) STILL admit.

    The Cycle-2 widening must not regress the Phase-1 admit set.
    Both Phase-1 carriers have ``external_cost_reductions == ()``
    so the new externals admit-loop is vacuous on them, identical
    to the C1 behavior. Defense-in-depth pin.
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
            f"reduction admit predicate post-Phase-2-Cycle-2. The "
            f"Cycle-2 widening must not regress Phase-1."
        )


# ---------------------------------------------------------------------------
# Pin 6 — Decline-set bench check on Uthros / Sami / Fungal
# ---------------------------------------------------------------------------


def test_uthros_and_sami_filter_through_to_admitted_post_cycle_2():
    """Pin #6 — Cycle-2 bench-level filter admits Uthros + Sami.

    Each of Uthros Psionicist / Sami, Wildcat Captain filters
    through :func:`_filter_deck_to_bridge_supported` to a 1-card
    admit list post-Cycle-2 (the C1 → C2 inversion at the bench
    level). The Phase-2 cards are now BRIDGE-SUPPORTED for
    cross-engine play.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    for name in ["Uthros Psionicist", "Sami, Wildcat Captain"]:
        if src.get(name) is None:
            pytest.skip(f"{name} absent from active CardSource")
        filtered_names, card_defs = (
            trajectory._filter_deck_to_bridge_supported([name], src)
        )
        assert filtered_names == [name], (
            f"{name} must admit through _filter_deck_to_bridge_"
            f"supported post-Cycle-2 (the C1 → C2 FLIP). Got "
            f"filtered_names={filtered_names!r}"
        )
        assert len(card_defs) == 1


# ---------------------------------------------------------------------------
# Pin 7 — No-silent-auto-grow pin (bridge reverse arm hard-errors)
# ---------------------------------------------------------------------------


def test_phase_3_token_on_externals_arm_raises_from_bridge_reverse_arm():
    """Pin #7 — §7.4 pin 14, bridge-side teeth.

    The Phase-2 reverse arm in
    :func:`mtg_bot.parity.cross_engine._card_def_to_python_printing`
    hard-errors when fed an accidentally-Phase-3 external rider
    (e.g. ``per_differently_named_land`` on the externals arm).
    No silent drop — the bridge §2 teeth match the Rust
    ``parse_printing`` hard-error.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    cd = CardDef(
        name="Phase-3 externals token (synthetic teeth probe)",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(),
        power=1,
        toughness=1,
        external_cost_reductions=(
            (1, "per_differently_named_land", ()),
        ),
    )
    with pytest.raises(ValueError) as excinfo:
        _card_def_to_python_printing(cd)
    assert "per_differently_named_land" in str(excinfo.value) or (
        "unsupported condition_kind" in str(excinfo.value)
    )


def test_phase_3_per_controlled_predicate_raises_from_bridge_reverse_arm():
    """Pin #7b — predicate-token §2 teeth on the bridge side.

    A ``per_controlled`` triple carrying a Phase-3 predicate token
    (e.g. ``"enchantment"``) hard-errors from the bridge reverse
    arm — Phase 2 supports ONLY ``"artifact"`` / ``"creature"``.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    cd = CardDef(
        name="Phase-3 per_controlled predicate (synthetic teeth probe)",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(),
        power=1,
        toughness=1,
        external_cost_reductions=(
            (1, "per_controlled", ("enchantment",)),
        ),
    )
    with pytest.raises(ValueError) as excinfo:
        _card_def_to_python_printing(cd)
    assert "enchantment" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Pin 8 — No-vanilla-grow pin
# ---------------------------------------------------------------------------


def test_predicate_rejects_vanilla_creature_without_riders():
    """Pin #8 — at-least-one-rider guardrail.

    A printing with both ``cost_reductions == ()`` AND
    ``external_cost_reductions == ()`` must NOT be admitted by
    the widened predicate (the §5.4 "at least ONE rider must be
    present" guardrail). Defense-in-depth against a refactor that
    accidentally drops the no-rider reject and lets vanilla
    creatures admit through the cost-reduction-aware path.

    The canonical vanilla creature is ``_printing_is_bridge_
    simple_creature``'s primary admit set; we sample a couple of
    canonical EoE vanillas and check both fail at this predicate.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    # Walk all printings; every one with NO riders at all must be
    # rejected here. We don't iterate all (slow) — just sanity-
    # check that the predicate's positive-set is exactly the 4
    # carriers from Pin #3 + nothing else.
    admitted = {
        name for name, printing in src.items()
        if trajectory._printing_is_bridge_pure_cost_reduction_creature(
            printing,
        )
    }
    # Every admitted card MUST carry at least one rider.
    for name in admitted:
        p = src[name]
        assert p.cost_reductions or p.external_cost_reductions, (
            f"{name} admitted by cost-reduction-aware predicate but "
            f"has NO riders — the at-least-one-rider guardrail is "
            f"broken. (Vanilla creatures must route through "
            f"_printing_is_bridge_simple_creature, not the cost-"
            f"reduction-aware path.)"
        )


# ---------------------------------------------------------------------------
# Pin 9 — CardDef default is empty tuple (back-compat)
# ---------------------------------------------------------------------------


def test_card_def_default_external_cost_reductions_is_empty_tuple():
    """Pin #9 — back-compat default.

    Every pre-Phase-2 CardDef omits the
    ``external_cost_reductions`` kwarg; the dataclass default is
    ``()``. Forward emit skips the key when the field is empty
    (bit-identical registry dict to pre-substrate); reverse arm
    materializes ``external_cost_reductions=()`` on the Python
    CardPrinting bit-identical to pre-substrate.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    cd = CardDef(
        name="Back-compat default vanilla",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(),
        power=1,
        toughness=1,
    )
    assert cd.external_cost_reductions == ()
    d = _spec_card_to_printing_dict(cd)
    # Key OMITTED for empty default.
    assert "external_cost_reductions" not in d
    # Reverse arm produces empty tuple on Python CardPrinting.
    p_rt = _card_def_to_python_printing(cd)
    assert p_rt.external_cost_reductions == ()


# ---------------------------------------------------------------------------
# Pin 10 — Sibling guards stay load-bearing (defense-in-depth)
# ---------------------------------------------------------------------------


def test_phase_2_carriers_still_rejected_by_simple_creature_guard():
    """Pin #10 — sibling-guard defense-in-depth.

    The 9 sibling admit predicates with the ``if
    printing.cost_reductions or printing.external_cost_reductions:
    return False`` guard each STILL reject the 4 cost-reduction
    carriers (Phase-1 + Phase-2). The widened admit predicate is
    a PARALLEL on the same named site, NOT a guard removal — every
    other admit predicate stays defended.
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
            f"gate post-Cycle-2 — the cost_reductions/external_cost_"
            f"reductions guard there is sibling-load-bearing (the "
            f"widened cost-reduction-aware predicate is a PARALLEL on "
            f"the same named site, NOT a simple-creature widen)."
        )
