"""**Carrier-AA substrate Phase 4E Cycle 2 (2026-05-26) — partial-FLIP.**

Tests for the Phase 4E Cycle 2 Python admit widen + partial-FLIP landing
per ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.7 (Python bridge
spec) + §6.5 (test plan, pins #32-34, #38-39) + §7.5 (cycle plan).

Cycle 2 deliverables (partial-FLIP per honest-stop on the "any" coin
Rust substrate gap — see SEARCH_LIMITATIONS):

  - ``_carrier_aa_phase_1_effect_classes`` widen: 7 → 9 entries
    (``DrawCardsByConditionMultiplier`` + ``AddManaToPool``).
  - ``_aa_is_phase1_sub_shape_a`` AA-rider gate widen: lift the
    ``is_mana_ability=True`` decline arm.
  - ``_python_aa_to_safe_dict`` bridge-floor widens:
      * Lift ``is_mana_ability=True`` decline arm.
      * Emit ``"is_mana_ability": True`` on the AA dict.
      * Add ``AddManaToPool`` forward arm with explicit "any" color
        honest-decline + ``spend_restriction`` honest-decline +
        single-pair restriction (Rust struct-variant carries SCALAR
        color + amount).
  - All-Fates Scroll partial-FLIP:
      * Per-AA admit predicate: DECLINED → ADMITTED (both AAs pass).
      * Printing-level Artifact admit predicate: DECLINED → ADMITTED.
      * Cross-engine builder gate: STAYS DECLINED (the "any" color
        teeth at the bridge floor in ``AddManaToPool`` forward arm).
        The full FLIP defers to Phase 4E C2.5 (Rust ManaPool "any"
        coin substrate).

**Partial-FLIP rationale (Option-honest-stop per worker prompt).** The
design doc §4.4.1 originally claimed Rust's
``Effect::AddManaToPool`` admits ``produces=(("any", 1),)`` via the
"any" color discriminator. **Verify-first invalidated that claim** —
Rust's ``validate_mana_symbol`` (``cards.rs:15888``) is a closed vocab
over ``{"W","U","B","R","G","C"}`` and ``register_printing`` raises
``ValueError: unknown mana symbol "any"``. The ``ManaPool`` substrate
at ``state.rs:942`` lacks an "any" coin slot in ``push_coins`` (the
``_ => return`` defensive no-op would silently drop "any" coins at
resolve time). Both Option A (validator widen alone) and Option B
(``PendingDecision::ManaColorChoice`` fan-out) are out of scope for a
"Python admit widen" cycle:

  * **Option A (eventual path):** widen Rust's ``validate_mana_symbol``
    + add ``ManaPool.any`` slot + ``push_coins`` arm for ``b'A'``
    byte + drain/payment semantics that satisfy "any" coin → any
    color request. Multi-cycle Rust substrate work — beyond C2's
    scope. Phase 4E C2.5 is the follow-up cycle.
  * **Option B:** ``PendingDecision::ManaColorChoice`` substrate would
    require the AA[0] resolve to push a decision (the agent picks a
    color at activation time, then Rust mints that color). But
    ``is_mana_ability=True`` AAs bypass the stack per CR 605 — the
    decision substrate fundamentally doesn't compose with the
    bypass-stack property. Rejected.

C2 ships the partial-FLIP — All-Fates Scroll moves from "declined at
per-AA admit predicate" (Phase 4E C1 state) to "declined at the
cross-engine builder gate" (Phase 4E C2 state). The loader-side
BLOCKED-SG admit set is UNCHANGED post-C2; the pool-parity row delta
defers to C2.5 (full FLIP + pool-parity regen).

**Test plan (per design doc §6.5 pins #32-34, #38-39):**

  #32. Effect-class widen pin: ``DrawCardsByConditionMultiplier`` +
       ``AddManaToPool`` both in ``_carrier_aa_phase_1_effect_classes``.
  #33. AA-rider gate widen pin: ``is_mana_ability=True`` AA passes
       ``_aa_is_phase1_sub_shape_a`` (synthetic AA shaped like
       All-Fates Scroll's AA[0] with a W-color produce so it round-
       trips end-to-end).
  #34. All-Fates Scroll admit predicate inversion pin: both AAs pass
       ``_aa_is_phase1_sub_shape_a``; printing-level Artifact admit
       predicate passes; the cross-engine builder gate STAYS DECLINED
       on the "any" color teeth.
  #38. ``is_mana_ability`` rider round-trip pin: a synthetic AA with
       ``is_mana_ability=True`` + ``AddManaToPool(produces=(("W",
       1),))`` (W color, not "any") round-trips through
       ``_python_aa_to_safe_dict`` + ``_aa_dict_to_python_activated_
       ability``; the dict carries ``"is_mana_ability": True``.
  #39. ``AddManaToPool`` resolve happy-path pin: a synthetic single-
       pair ``AddManaToPool(produces=(("W", 1),))`` admits through
       the bridge forward arm (the "any" color teeth applies only
       to "any" — single-pair W/U/B/R/G/C admit clean).

Plus per-card probe — All-Fates Scroll-shaped synthetic exercises
the partial-FLIP via a synthetic W-color AA[0] shape (the "any" coin
isn't yet round-trip-able, so the per-card probe uses a synthetic
that's structurally identical but uses a closed-vocab color so the
full bridge round-trip succeeds end-to-end; the live "any" path lands
at C2.5).
"""

from __future__ import annotations

import dataclasses
import json
import pytest


# ---------------------------------------------------------------------------
# §6.5 #32 — Effect-class admit-set widen
# ---------------------------------------------------------------------------


def test_phase_4e_c2_effect_class_widen_adds_two_entries():
    """**§6.5 #32.** ``_carrier_aa_phase_1_effect_classes`` grows from
    7 → 9 entries at Phase 4E C2; ``DrawCardsByConditionMultiplier`` +
    ``AddManaToPool`` are the two new additions. The 7 prior entries
    stay admitted (no regression).

    Post-Phase-4C-C2: the admit set grew from 9 → 11 with the two
    Ghost Vacuum AA Effect classes; this pin pins the Phase-4E-C2 +
    pin on the admit-set invariant (the 9 Phase-4E-C2 entries must
    still be present). The +2 cardinality assertion lifts to >=9 so
    later sub-phase widens don't break this pin.
    """
    from mtg_bot.effects.generic.become_type import (
        BecomesCopyOfTargetLand,
    )
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.effects.generic.exile import (
        ExileAllGraveyards,
        ExileTargetAttackingCreatureUntilEndStep,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity.trajectory import (
        _carrier_aa_phase_1_effect_classes,
    )

    admitted = _carrier_aa_phase_1_effect_classes()
    # New widens.
    assert DrawCardsByConditionMultiplier in admitted
    assert AddManaToPool in admitted
    # No regression.
    for cls in (
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
    ):
        assert cls in admitted, (
            f"Phase 4E C2 no-regression: {cls.__name__} dropped from "
            "the Effect-class admit set"
        )
    # Lower-bound invariant -- subsequent sub-phase widens (Phase 4C
    # C2 grew the admit set 9 -> 11 for the Ghost Vacuum Effect
    # classes; Phase 4D C2 added 2 more for Keys to the House) are
    # strictly additive on this Phase-4E-C2 baseline.
    assert len(admitted) >= 9


# ---------------------------------------------------------------------------
# §6.5 #33 — AA-rider gate widen (is_mana_ability=True now admitted)
# ---------------------------------------------------------------------------


def test_phase_4e_c2_aa_rider_gate_admits_is_mana_ability():
    """**§6.5 #33.** ``_aa_is_phase1_sub_shape_a`` admits a synthetic
    AA shaped like All-Fates Scroll's AA[0] but with a W-color produce
    so the bridge round-trip floor (which still honest-declines "any")
    isn't on this pin's critical path. The point of pin #33 is the
    AA-rider gate widen alone; pin #34 + per-card probe cover the
    "any" teeth at the builder gate.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(produces=(("W", 1),)),
        is_mana_ability=True,
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True, (
        "Phase 4E C2 widen: a synthetic mana-ability AA with a "
        "closed-vocab color produce must PASS the per-AA admit gate "
        "(the is_mana_ability=True rider teeth is lifted)"
    )


def test_phase_4e_c2_aa_rider_gate_still_declines_sorcery_speed():
    """**§6.5 #33 negative -- INVERTED post-Phase-4C-C2 / Phase-4D-C2.**
    Lifting ``is_mana_ability`` at Phase 4E C2 doesn't silently lift
    other riders. Pre-C2 the ``sorcery_speed=True`` rider stayed
    decline; post-Phase-4C-C2 (Ghost Vacuum admit) and post-Phase-4D-
    C2 (Keys to the House admit) it admits. This pin asserts the
    post-C2 state.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(produces=(("W", 1),)),
        sorcery_speed=True,  # Now admitted as of Phase 4C C2 / 4D C2
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True, (
        "Post-Phase-4C-C2 / 4D-C2: sorcery_speed=True is now admitted "
        "at the per-AA admit gate (Phase 4C C2 Ghost Vacuum + Phase "
        "4D C2 Keys to the House widens). This pin previously "
        "asserted decline; the inversion is sibling of the Ghost "
        "Vacuum + Keys to the House FLIPs."
    )


# ---------------------------------------------------------------------------
# §6.5 #34 — All-Fates Scroll partial-FLIP (admit predicate ↔ builder gate)
# ---------------------------------------------------------------------------


def test_phase_4e_c2_all_fates_scroll_predicate_passes_post_widens():
    """**§6.5 #34 (predicate side).** All-Fates Scroll's live printing
    now PASSES the printing-level Artifact admit predicate post-Phase-
    4E-C2 widens (per-AA gate lifted ``is_mana_ability`` + Effect-
    class admits ``AddManaToPool`` + ``DrawCardsByConditionMultiplier``).
    """
    from mtg_bot.cards.parser_source import _build_artifact_printing
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        c for c in raw_cards if c.get("name") == "All-Fates Scroll"
    )
    printing = _build_artifact_printing(raw)
    aa0, aa1 = printing.activated_abilities

    assert _aa_is_phase1_sub_shape_a(aa0) is True, (
        "AA[0] must pass per-AA gate (is_mana_ability + AddManaToPool "
        "Effect-class teeth both lifted at C2)"
    )
    assert _aa_is_phase1_sub_shape_a(aa1) is True, (
        "AA[1] must pass per-AA gate (DrawCardsByConditionMultiplier "
        "Effect-class teeth lifted at C2)"
    )
    assert _printing_is_bridge_simple_carrier_aa_artifact(printing) is True
    assert _printing_is_bridge_simple_carrier_aa_any(printing) is True


def test_phase_4e_c2_all_fates_scroll_builder_gate_declines_on_any_teeth():
    """**§6.5 #34 (builder side — partial-FLIP teeth).** The cross-
    engine builder STILL returns None on All-Fates Scroll because the
    bridge floor's ``AddManaToPool`` forward arm honest-declines the
    ``produces=(("any", 1),)`` shape.
    """
    from mtg_bot.cards.parser_source import _build_artifact_printing
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict
    from mtg_bot.parity.trajectory import _carrier_aa_artifact_card_def

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        c for c in raw_cards if c.get("name") == "All-Fates Scroll"
    )
    printing = _build_artifact_printing(raw)
    aa0 = printing.activated_abilities[0]

    # AA[0] bridge floor honest-declines on the "any" teeth.
    assert _python_aa_to_safe_dict(aa0) is None, (
        "Phase 4E C2 partial-FLIP teeth: AA[0] AddManaToPool "
        "produces=(('any', 1),) must DECLINE at the bridge floor "
        "(Rust validate_mana_symbol closed vocab — Phase 4E C2.5 "
        "ships the ManaPool 'any' coin substrate)"
    )
    # Builder gate returns None → loader-side decline.
    assert _carrier_aa_artifact_card_def(printing) is None


# ---------------------------------------------------------------------------
# §6.5 #38 — is_mana_ability round-trip pin
# ---------------------------------------------------------------------------


def test_phase_4e_c2_is_mana_ability_round_trips_through_bridge_floor():
    """**§6.5 #38.** A synthetic AA with ``is_mana_ability=True`` +
    closed-vocab ``AddManaToPool`` survives the bridge floor's forward
    arm: the dict carries ``is_mana_ability=True``; the reverse arm
    reconstructs the AA byte-equal.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(produces=(("W", 1),)),
        is_mana_ability=True,
    )
    aa_dict = _python_aa_to_safe_dict(aa)
    assert aa_dict is not None, (
        "Synthetic W-color mana-ability AA must round-trip cleanly "
        "(the 'any' teeth applies only to 'any' color)"
    )
    assert aa_dict.get("is_mana_ability") is True, (
        "The is_mana_ability flag must propagate on the AA dict"
    )
    assert aa_dict["effect"]["kind"] == "add_mana_to_pool"
    assert aa_dict["effect"]["color"] == "W"
    assert aa_dict["effect"]["amount"] == 1
    # Reverse round-trip via _aa_dict_to_python_activated_ability.
    aa_back = _aa_dict_to_python_activated_ability(aa_dict)
    assert aa_back == aa, (
        "Reverse arm must reconstruct the AA byte-equal at the "
        "ActivatedAbility __eq__ surface"
    )


def test_phase_4e_c2_is_mana_ability_false_does_not_emit_flag():
    """**§6.5 #38 negative.** When ``is_mana_ability=False``, the AA
    dict must NOT carry the ``is_mana_ability`` key (mirrors the
    Phase-1 empty-omit discipline on optional bool fields).
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=UntapTargetLand(),
        is_mana_ability=False,
    )
    aa_dict = _python_aa_to_safe_dict(aa)
    assert aa_dict is not None
    assert "is_mana_ability" not in aa_dict, (
        "Phase-1 empty-omit discipline: is_mana_ability=False must "
        "NOT emit the key on the AA dict"
    )


# ---------------------------------------------------------------------------
# §6.5 #39 — AddManaToPool forward-arm decline gates
# ---------------------------------------------------------------------------


def test_phase_4e_c2_add_mana_to_pool_admits_single_pair_closed_vocab():
    """**§6.5 #39 (admit side).** Single-pair ``AddManaToPool`` with a
    closed-vocab W/U/B/R/G/C color admits at the bridge floor — the
    "any" teeth applies only to "any", not to a missing parameterized
    grammar.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    for color in ("W", "U", "B", "R", "G", "C"):
        aa = ActivatedAbility(
            cost=ActivationCost(tap_self=True),
            effect=AddManaToPool(produces=((color, 1),)),
            is_mana_ability=True,
        )
        aa_dict = _python_aa_to_safe_dict(aa)
        assert aa_dict is not None, (
            f"Single-pair AddManaToPool with color={color!r} must "
            "admit at the bridge floor"
        )
        assert aa_dict["effect"]["color"] == color


def test_phase_4e_c2_add_mana_to_pool_declines_any_color():
    """**§6.5 #39 (decline side — "any" teeth).** ``AddManaToPool``
    with an "any" color discriminator honest-declines at the bridge
    floor — the Rust ``validate_mana_symbol`` closed vocab + the
    ``ManaPool`` substrate gap is the underlying constraint; Phase
    4E C2.5 closes the gap.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(produces=(("any", 1),)),
        is_mana_ability=True,
    )
    assert _python_aa_to_safe_dict(aa) is None, (
        "Phase 4E C2 partial-FLIP teeth: 'any' color AddManaToPool "
        "must DECLINE at the bridge floor"
    )


def test_phase_4e_c2_add_mana_to_pool_declines_multi_pair():
    """**§6.5 #39 (decline side — multi-pair teeth).** A multi-pair
    ``AddManaToPool`` (e.g. ``Add WUBRG``) declines at the bridge
    floor — Rust's ``Effect::AddManaToPool`` struct-variant carries a
    SCALAR ``color`` + ``amount`` (one color per Effect instance).
    Multi-color batched mana would need a Rust schema bump.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(
            produces=(("W", 1), ("U", 1), ("B", 1), ("R", 1), ("G", 1)),
        ),
        is_mana_ability=True,
    )
    assert _python_aa_to_safe_dict(aa) is None, (
        "Multi-pair AddManaToPool must DECLINE at the bridge floor "
        "(Rust struct-variant single-color contract)"
    )


def test_phase_4e_c2_add_mana_to_pool_declines_spend_restriction():
    """**§6.5 #39 (decline side — spend_restriction teeth).** A
    ``spend_restriction``-tagged ``AddManaToPool`` declines — Rust's
    ``Effect::AddManaToPool`` carries no equivalent field today
    (Phase N feature). All-Fates Scroll's AA[0] carries
    ``spend_restriction=None`` so this guard doesn't affect the FLIP.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(
            produces=(("C", 1),),
            spend_restriction="colorless_eldrazi",
        ),
        is_mana_ability=True,
    )
    assert _python_aa_to_safe_dict(aa) is None, (
        "spend_restriction-tagged AddManaToPool must DECLINE at the "
        "bridge floor (Rust schema gap — Phase N)"
    )


def test_phase_4e_c2_add_mana_to_pool_declines_negative_amount():
    """**§6.5 #39 (defense in depth).** A negative ``amount``
    declines — Rust's parser raises on ``amount < 0`` (mirrors the
    floor at ``cards.rs:12196``).
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(produces=(("W", -1),)),
        is_mana_ability=True,
    )
    assert _python_aa_to_safe_dict(aa) is None


# ---------------------------------------------------------------------------
# Per-card probe — All-Fates Scroll-shaped synthetic + live decline trace
# ---------------------------------------------------------------------------


def test_phase_4e_c2_all_fates_scroll_synthetic_w_variant_full_round_trip():
    """**Per-card probe — synthetic FLIP-ready variant.** A synthetic
    All-Fates Scroll-shaped Artifact carrier whose AA[0] uses a closed-
    vocab "W" color (instead of "any") round-trips end-to-end at the
    cross-engine builder gate. Pin proves the Phase 4E C2 substrate
    work is complete and the ONLY remaining teeth is the Rust
    ``ManaPool`` "any" coin gap (C2.5 follow-up cycle).

    Constructs a CardPrinting with:
      * AA[0]: ``AddManaToPool(produces=(("W", 1),))`` + is_mana_ability
      * AA[1]: ``DrawCardsByConditionMultiplier`` (PerDifferentlyNamed
        Land) + ``{7}, {T}, Sac`` cost
    """
    from mtg_bot.cards.parser_source import _build_artifact_printing
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_artifact_card_def,
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        c for c in raw_cards if c.get("name") == "All-Fates Scroll"
    )
    live_printing = _build_artifact_printing(raw)
    aa0_live, aa1_live = live_printing.activated_abilities

    # Build a synthetic AA[0] with "W" instead of "any" (drop-in
    # replacement of the effect).
    aa0_synth = dataclasses.replace(
        aa0_live,
        effect=AddManaToPool(produces=(("W", 1),)),
    )
    # Build the synthetic printing.
    synth = dataclasses.replace(
        live_printing,
        activated_abilities=(aa0_synth, aa1_live),
    )

    # Per-AA gate.
    assert _aa_is_phase1_sub_shape_a(aa0_synth) is True
    assert _aa_is_phase1_sub_shape_a(aa1_live) is True
    # Printing-level admit predicate.
    assert _printing_is_bridge_simple_carrier_aa_artifact(synth) is True
    # Cross-engine builder: NOW returns a non-None CardDef (the "any"
    # teeth is gone in the synthetic).
    cd = _carrier_aa_artifact_card_def(synth)
    assert cd is not None, (
        "Synthetic All-Fates Scroll with W-color AA[0] must round-"
        "trip end-to-end through the cross-engine builder; the only "
        "live-EoE teeth left for All-Fates Scroll is the 'any' coin "
        "Rust ManaPool substrate gap (Phase 4E C2.5)"
    )
    assert cd.card_type == "Artifact"
    assert len(cd.activated_abilities) == 2
    # AA[0] dict shape.
    aa0_dict = cd.activated_abilities[0]
    assert aa0_dict["effect"]["kind"] == "add_mana_to_pool"
    assert aa0_dict["effect"]["color"] == "W"
    assert aa0_dict["effect"]["amount"] == 1
    assert aa0_dict.get("is_mana_ability") is True
    # AA[1] dict shape (DrawCardsByConditionMultiplier).
    aa1_dict = cd.activated_abilities[1]
    assert (
        aa1_dict["effect"]["kind"]
        == "draw_cards_by_condition_multiplier"
    )
    assert (
        aa1_dict["effect"]["condition_tag"]
        == "per_differently_named_land"
    )


def test_phase_4e_c2_all_fates_scroll_live_partial_flip_trace():
    """**Per-card probe — live All-Fates Scroll partial-FLIP trace.**
    Walks the live admit chain end-to-end and asserts:
      1. Each AA passes the per-AA admit predicate.
      2. The printing-level Artifact admit predicate passes.
      3. AA[0] fails the bridge floor (the "any" teeth).
      4. The cross-engine builder returns None.

    This is the explicit teeth-trace for the partial-FLIP. The full
    FLIP defers to Phase 4E C2.5 (Rust ``ManaPool`` "any" coin
    substrate).
    """
    from mtg_bot.cards.parser_source import _build_artifact_printing
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_artifact_card_def,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        c for c in raw_cards if c.get("name") == "All-Fates Scroll"
    )
    printing = _build_artifact_printing(raw)
    aa0, aa1 = printing.activated_abilities

    # 1. Per-AA admit predicate: BOTH AAs pass.
    assert _aa_is_phase1_sub_shape_a(aa0) is True
    assert _aa_is_phase1_sub_shape_a(aa1) is True
    # 2. Printing-level admit predicate: passes.
    assert _printing_is_bridge_simple_carrier_aa_artifact(printing) is True
    assert _printing_is_bridge_simple_carrier_aa_any(printing) is True
    # 3. AA[0] bridge floor: declines on the "any" teeth.
    assert _python_aa_to_safe_dict(aa0) is None
    # AA[1] bridge floor: PASSES (the DrawCardsByConditionMultiplier
    # arm is fully wired at C1).
    aa1_dict = _python_aa_to_safe_dict(aa1)
    assert aa1_dict is not None
    assert (
        aa1_dict["effect"]["kind"]
        == "draw_cards_by_condition_multiplier"
    )
    # 4. Cross-engine builder: returns None (the all-or-nothing
    # bridge-floor contract — AA[0] fails, builder declines the
    # whole printing).
    assert _carrier_aa_artifact_card_def(printing) is None


# ---------------------------------------------------------------------------
# Pre-existing carriers stay-admitted post-C2 (no regression)
# ---------------------------------------------------------------------------


def test_phase_4e_c2_no_regression_on_phase_1_3_carriers():
    """**Phase 4E C2 no-regression pin.** Every Phase-1-3 Carrier-AA
    admit (Swarmyard + Deserted Temple + Petrified Field + Terrain
    Generator + Mystifying Maze + Scavenger Grounds + Thespian's Stage)
    stays admitted at the cross-engine builder gate post-C2 widens.
    The C2 widens are strictly additive on the Effect-class +
    is_mana_ability axes; the pre-existing 7 Phase-1-3 admits are
    single-AA non-mana-ability AAs that don't intersect the new
    widens' axes.
    """
    from mtg_bot.cards.parser_source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _carrier_aa_land_card_def

    ps = OracleParserCardSource().get_printings()
    for name in (
        "Swarmyard",
        "Deserted Temple",
        "Petrified Field",
        "Terrain Generator",
        "Mystifying Maze",
        "Scavenger Grounds",
        "Thespian's Stage",
    ):
        p = ps[name]
        cd = _carrier_aa_land_card_def(p)
        assert cd is not None, (
            f"Phase 4E C2 no-regression: {name} must still admit at "
            f"the cross-engine builder gate post-C2 widens"
        )


# ---------------------------------------------------------------------------
# Mirrorpool / Ghost Vacuum / Keys to the House stay declined post-C2
# (no-silent-auto-grow on the other Phase-4 carriers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    # Post-Phase-4C-C2 + Phase-4D-C2: Ghost Vacuum + Keys to the House
    # have FLIPped DECLINED -> ADMITTED. Only Mirrorpool still declines
    # (4B ships its 2 Effect-class widens — spell-copy + token-copy).
    ["Mirrorpool"],
)
def test_phase_4e_c2_other_phase_4_carriers_stay_declined(name):
    """**Phase 4E C2 no-silent-auto-grow pin (post-Phase-4C-C2 +
    Phase-4D-C2).** The remaining Phase-4 multi-AA carrier that
    hasn't yet shipped its FLIP (Mirrorpool) STAYS DECLINED. Ghost
    Vacuum + Keys to the House were here pre-C2 but have FLIPped
    ADMITTED via the Phase 4C C2 + Phase 4D C2 widens (Effect-class
    + sorcery_speed AA-rider). Phase 4B ships the Mirrorpool widens
    (CopyTargetInstantOrSorceryYouControl +
    CreateTokenCopyOfTargetCreatureYouControl).
    """
    from mtg_bot.cards.parser_source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _carrier_aa_artifact_card_def,
        _carrier_aa_land_card_def,
        _printing_is_bridge_simple_carrier_aa_any,
    )

    ps = OracleParserCardSource().get_printings()
    p = ps[name]
    # Both predicate and builder must decline.
    assert _printing_is_bridge_simple_carrier_aa_any(p) is False, (
        f"{name} must STAY DECLINED at the dispatcher post-Phase-4E-"
        f"C2 + Phase-4C-C2 + Phase-4D-C2 (Phase 4B ships the Mirrorpool "
        f"widens)"
    )
    assert _carrier_aa_land_card_def(p) is None
    assert _carrier_aa_artifact_card_def(p) is None
