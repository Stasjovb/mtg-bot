"""**Carrier-AA substrate Phase 4B Cycle 4 (2026-05-26).**

Python-only landing per ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md``
§5.4 + §7.2 row C4 — closes the Option A FLIP for Mirrorpool.

Predecessors (origin/main):

  * C1 (commit ``434d6aa1`` rebased + merged via ``818b4c64``) — Rust
    AA[1] (``CreateTokenCopyOfTargetCreatureYouControl``, CR-707.5
    token-creature-copy) substrate.
  * C2 (commit ``58988ade``) — Python admit widen for AA[1] only
    (Option A partial widen + honest-stop on AA[0] Rust gap).
  * C3 (commit ``e5cd1c18``) — Rust AA[0]
    (``CopyTargetInstantOrSorceryYouControl``, CR-707.2 spell-copy)
    substrate (Effect variant + parse + to_pydict + stack-target
    fan-out + validation + push-copy resolve + ``StackItem.is_copy``
    bookkeeping).

C4 closes the Python half end-to-end:

  1. **Effect-class admit widen** — adds
     ``CopyTargetInstantOrSorceryYouControl`` to
     :func:`mtg_bot.parity.trajectory._carrier_aa_phase_1_effect_classes`.
     The admit set bumps 14 → 15.
  2. **Forward arm** in
     :func:`mtg_bot.parity.cross_engine._python_aa_to_safe_dict`
     emits ``{"kind": "copy_target_instant_or_sorcery_you_control"}``
     (unit variant — no rider keys).
  3. **Reverse arm** in
     :func:`mtg_bot.parity.cross_engine._ta_dict_to_python_effect`
     constructs ``CopyTargetInstantOrSorceryYouControl()``.
  4. **Mirrorpool FLIP** — under the Phase 4A multi-AA all-or-nothing
     gate, both per-AA Effect classes now admit; Mirrorpool's
     printing-level admit FLIPs DECLINED → ADMITTED. First Phase-4
     multi-AA carrier to FULLY FLIP end-to-end.
  5. **Walk inversion** in
     ``tests/test_carrier_aa_phase_4a_substrate_cycle_1.py`` —
     Mirrorpool moves OUT of ``PHASE_4_DECLINED_CARRIERS`` and INTO
     ``PHASE_1_3_ADMITTED_LAND_CARRIERS``; the decline-set is now
     empty (the standalone sentinel
     ``test_phase_4_declined_carriers_set_is_empty_post_4b_c4``
     asserts the emptiness invariant).
  6. **Bridge round-trip + admit-now-passes test pins** — this file.

ZERO Rust changes (Python-only widen). C5 ships the per-card real-EoE
probe per design doc §6.7 (AA[0] spell-copy line + AA[1] token-copy
line on a live Mirrorpool printing).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# C4 admit-set sentinel — admit set bumps to 15 classes
# ---------------------------------------------------------------------------


def test_phase_4b_c4_admit_set_widened_by_exactly_one():
    """**Phase 4B C4 sentinel — the Effect-class admit set grows by
    exactly 1 (AA[0]'s ``CopyTargetInstantOrSorceryYouControl`` in).**

    Sibling of the C2 sentinel
    ``test_phase_4b_c2_admit_set_widened_by_exactly_one`` but for the
    second half of the Option A widen.
    """
    from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand
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
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
        AddManaToPool,
    )
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity.trajectory import _carrier_aa_phase_1_effect_classes

    admit_set = _carrier_aa_phase_1_effect_classes()
    # Expected post-C4 admit set (post-rebase-onto-Spacecraft-P4-C2):
    # Phase 1-3 (7) + Phase 4C C2 (2) + Phase 4D C2 (2) + Phase 4E C2
    # (2) + Phase 4B C2 (1) + Spacecraft Phase 4 C2 (1) + Phase 4B
    # C4 (1) = 16.
    expected_post_c4 = frozenset({
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
        DrawCardsByConditionMultiplier,
        AddManaToPool,
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
        LockOrUnlockDoorOfTargetRoomYouControl,
        SearchLibraryForCard,
        CreateTokenCopyOfTargetCreatureYouControl,
        # Spacecraft Phase 4 C2 (rebase pickup):
        AddChargeCounterManaOfChosenColor,
        # Phase 4B C4 (the new one):
        CopyTargetInstantOrSorceryYouControl,
    })
    assert admit_set == expected_post_c4, (
        "Phase 4B C4 admit set sentinel: post-C4 admit set must be "
        f"the 16-class set (rebased onto Spacecraft P4 C2); got "
        f"{len(admit_set)} classes, delta = added "
        f"{admit_set - expected_post_c4} / "
        f"missing {expected_post_c4 - admit_set}"
    )
    assert len(admit_set) == 16, (
        f"Phase 4B C4 admit-set size sentinel: expected 16 classes "
        f"post-C4 (rebased onto Spacecraft P4 C2 at ``4a2485f1``); "
        f"got {len(admit_set)}"
    )
    assert CopyTargetInstantOrSorceryYouControl in admit_set, (
        "Phase 4B C4 FLIP: CopyTargetInstantOrSorceryYouControl must "
        "BE in _carrier_aa_phase_1_effect_classes post-C4."
    )


# ---------------------------------------------------------------------------
# C4 bridge round-trip — forward + reverse arms for AA[0]
# ---------------------------------------------------------------------------


def test_bridge_forward_arm_copy_target_instant_or_sorcery_aa0():
    """**Phase 4B C4 forward-arm pin.** A synthetic Mirrorpool-AA[0]-
    shape ActivatedAbility forward-emits a non-None dict with the
    canonical ``copy_target_instant_or_sorcery_you_control`` kind.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=3),
        ),
        effect=CopyTargetInstantOrSorceryYouControl(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Phase 4B C4 invariant: AA[0]'s forward arm must emit a non-"
        "None dict post-C4."
    )
    assert d["effect"] == {
        "kind": "copy_target_instant_or_sorcery_you_control",
    }, (
        f"Phase 4B C4 invariant: AA[0]'s forward arm must emit the "
        f"canonical unit-variant kind; got {d['effect']!r}"
    )


def test_bridge_reverse_arm_copy_target_instant_or_sorcery_aa0():
    """**Phase 4B C4 reverse-arm pin.** A ``copy_target_instant_or_
    sorcery_you_control`` dict reverse-constructs a
    ``CopyTargetInstantOrSorceryYouControl`` instance.
    """
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    effect = _ta_dict_to_python_effect({
        "kind": "copy_target_instant_or_sorcery_you_control",
    })
    assert isinstance(effect, CopyTargetInstantOrSorceryYouControl), (
        f"Phase 4B C4 invariant: reverse arm must construct a "
        f"CopyTargetInstantOrSorceryYouControl instance; got "
        f"{type(effect).__name__}"
    )


def test_bridge_round_trip_copy_target_instant_or_sorcery_aa0():
    """**Phase 4B C4 round-trip pin.** A Mirrorpool-AA[0]-shape AA
    round-trips byte-equal through forward + reverse arms (a Python ->
    dict -> Python -> dict pair lands byte-equal at the second emit).
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=3),
        ),
        effect=CopyTargetInstantOrSorceryYouControl(),
    )
    d = _python_aa_to_safe_dict(aa_orig)
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig, (
        f"Phase 4B C4 round-trip: reverse-constructed AA must equal "
        f"the original; got {aa_back!r} vs {aa_orig!r}"
    )
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2, (
        f"Phase 4B C4 round-trip: second forward emit must be byte-"
        f"equal to the first; got {d2!r} vs {d!r}"
    )


# ---------------------------------------------------------------------------
# C4 per-AA admit FLIP — synthetic AA[0] shape
# ---------------------------------------------------------------------------


def test_synthetic_aa0_admit_now_passes_post_c4():
    """**Phase 4B C4 per-AA admit FLIP pin (synthetic).** A synthetic
    Mirrorpool-AA[0]-shape ActivatedAbility now PASSES
    :func:`_aa_is_phase1_sub_shape_a` (was DECLINED at C2/C3).
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=3),
        ),
        effect=CopyTargetInstantOrSorceryYouControl(),
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True, (
        "Phase 4B C4 invariant: a synthetic Mirrorpool-AA[0]-shape AA "
        "must PASS the per-AA admit predicate post-C4 — the Effect "
        "class is in the widened admit set."
    )


# ---------------------------------------------------------------------------
# C4 live Mirrorpool FLIP — printing-level admit gate
# ---------------------------------------------------------------------------


def test_mirrorpool_live_printing_flips_admitted_at_full_admit_gate_post_c4():
    """**Phase 4B C4 FLIP pin (live Mirrorpool printing).** The full
    Option A FLIP: both per-AA Effect classes are in the admit set;
    the multi-AA all-or-nothing gate passes; Mirrorpool's printing-
    level admit FLIPs DECLINED → ADMITTED.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    printings = OracleParserCardSource().get_printings()
    if "Mirrorpool" not in printings:
        pytest.skip(
            "Mirrorpool not in live EoE pool — skip the live-printing "
            "FLIP pin. The synthetic-shape sibling pin still exercises "
            "the C4 invariant.",
        )
    mp = printings["Mirrorpool"]
    assert len(mp.activated_abilities) == 2, (
        f"Mirrorpool should have 2 AAs (verified at C1 verify-first); "
        f"got {len(mp.activated_abilities)}"
    )
    aa0, aa1 = mp.activated_abilities[0], mp.activated_abilities[1]
    # Both per-AA gates pass post-C4.
    assert _aa_is_phase1_sub_shape_a(aa0) is True, (
        "Phase 4B C4 FLIP: live Mirrorpool's AA[0] must ADMIT at the "
        "per-AA admit gate post-C4."
    )
    assert _aa_is_phase1_sub_shape_a(aa1) is True, (
        "Phase 4B C2 invariant: live Mirrorpool's AA[1] admits at the "
        "per-AA admit gate (C2 widen at ``58988ade``)."
    )
    # Printing-level admit FLIPs ADMITTED at the Land predicate and
    # the unified dispatcher.
    assert _printing_is_bridge_simple_carrier_aa_land(mp) is True, (
        "Phase 4B C4 FLIP: live Mirrorpool's printing-level admit "
        "must FLIP ADMITTED on the Land predicate post-C4."
    )
    assert _printing_is_bridge_simple_carrier_aa_any(mp) is True, (
        "Phase 4B C4 FLIP: live Mirrorpool's printing-level admit "
        "must FLIP ADMITTED on the unified dispatcher post-C4."
    )


# ---------------------------------------------------------------------------
# C4 live Mirrorpool bridge round-trip — both AAs at the bridge floor
# ---------------------------------------------------------------------------


def test_mirrorpool_live_both_aas_round_trip_at_bridge_floor_post_c4():
    """**Phase 4B C4 bridge-floor round-trip pin (live Mirrorpool).**
    Pre-C4 (post-C1/C2/C3): AA[0]'s forward arm declined (the
    ``CopyTargetInstantOrSorceryYouControl`` class had no forward arm
    recognizer). Post-C4: both AAs emit non-None dicts and reverse-
    construct cleanly.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    printings = OracleParserCardSource().get_printings()
    if "Mirrorpool" not in printings:
        pytest.skip(
            "Mirrorpool not in live EoE pool — skip the live bridge-"
            "floor round-trip pin.",
        )
    mp = printings["Mirrorpool"]
    aa0, aa1 = mp.activated_abilities[0], mp.activated_abilities[1]

    aa0_dict = _python_aa_to_safe_dict(aa0)
    aa1_dict = _python_aa_to_safe_dict(aa1)
    assert aa0_dict is not None, (
        "Phase 4B C4 invariant: live Mirrorpool AA[0] must round-trip "
        "through the bridge floor post-C4."
    )
    assert aa1_dict is not None, (
        "Phase 4B C2 invariant: live Mirrorpool AA[1] round-trips "
        "through the bridge floor (C1 forward arm)."
    )
    assert aa0_dict["effect"] == {
        "kind": "copy_target_instant_or_sorcery_you_control",
    }
    assert aa1_dict["effect"] == {
        "kind": "create_token_copy_of_target_creature_you_control",
    }
    # Reverse-construct + assert Effect class round-trips. Note: the
    # live AA carries ``cost.mana.mana_str='{2}{C}'`` / ``'{4}{C}'``
    # but the bridge floor's dict form drops the rendered ``mana_str``
    # representation (only the structured ``generic`` field round-
    # trips). The reverse-constructed AA therefore has
    # ``mana_str=''`` — a known bridge-floor discipline (sibling of
    # other Phase 1-3 / 4C / 4D cards) — so this pin only asserts
    # Effect-class round-trip + structured cost fields.
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    aa0_back = _aa_dict_to_python_activated_ability(aa0_dict)
    aa1_back = _aa_dict_to_python_activated_ability(aa1_dict)
    assert isinstance(aa0_back.effect, CopyTargetInstantOrSorceryYouControl)
    assert isinstance(
        aa1_back.effect, CreateTokenCopyOfTargetCreatureYouControl,
    )
    # Structured cost fields are byte-equal even though mana_str isn't.
    assert aa0_back.cost.tap_self == aa0.cost.tap_self
    assert aa0_back.cost.sacrifice_self == aa0.cost.sacrifice_self
    assert aa0_back.cost.mana.generic == aa0.cost.mana.generic
    assert aa0_back.cost.mana.colored == aa0.cost.mana.colored
    assert aa1_back.cost.tap_self == aa1.cost.tap_self
    assert aa1_back.cost.sacrifice_self == aa1.cost.sacrifice_self
    assert aa1_back.cost.mana.generic == aa1.cost.mana.generic
    assert aa1_back.cost.mana.colored == aa1.cost.mana.colored


# ---------------------------------------------------------------------------
# C4 pool-parity invariant — no silent auto-grow at the printing-level admit
# ---------------------------------------------------------------------------


# Carrier-AA Phase-1-3 + Phase-4D + Phase-4B C4 Land admits. Pre-C4:
# 7 Lands + 4 spillover Lands = 11 Lands. C4 ADDS Mirrorpool. Post-C4:
# 12 Lands.
PHASE_1_3_4D_4B_ADMITTED_LAND_CARRIERS = (
    "Swarmyard",
    "Deserted Temple",
    "Petrified Field",
    "Terrain Generator",
    "Mystifying Maze",
    "Scavenger Grounds",
    "Thespian's Stage",
    "Crystal Quarry",
    "Eldrazi Temple",
    "Gemstone Caverns",
    "Sunken Citadel",
    # Phase 4B C4 (the new one).
    "Mirrorpool",
)

PHASE_4D_ADMITTED_ARTIFACT_CARRIERS = (
    "Keys to the House",
    "Ghost Vacuum",
    "All-Fates Scroll",
)


def test_full_pool_admit_set_grows_by_exactly_one_post_c4():
    """**Phase 4B C4 pool-parity invariant — no silent auto-grow.**

    Walks the FULL EoE pool and confirms the unified admit
    dispatcher :func:`_printing_is_bridge_simple_carrier_aa_any`
    returns EXACTLY the post-C4 expected set (post-C2 baseline +
    Mirrorpool). Sentinel that detects any silently-promoted-by-
    C4-widen card the audit didn't anticipate.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_any,
    )

    printings = OracleParserCardSource().get_printings()
    admitted = frozenset(
        name
        for name, p in printings.items()
        if _printing_is_bridge_simple_carrier_aa_any(p)
    )
    expected = frozenset(
        PHASE_1_3_4D_4B_ADMITTED_LAND_CARRIERS
        + PHASE_4D_ADMITTED_ARTIFACT_CARRIERS,
    )
    assert admitted == expected, (
        f"Phase 4B C4 pool-parity invariant: full-pool admit set must "
        f"be exactly the C2 baseline + Mirrorpool; got admit delta = "
        f"added {admitted - expected} / "
        f"missing {expected - admitted}"
    )
    # Mirrorpool MUST be in the admit set post-C4.
    assert "Mirrorpool" in admitted, (
        "Phase 4B C4 FLIP: Mirrorpool must be in the printing-level "
        "admit dispatcher post-C4."
    )


def test_phase_1_3_4d_4b_land_admit_set_unchanged_minus_mirrorpool_post_c4():
    """**Phase 4B C4 no-regression pin — the C2 baseline stays
    admitted post-C4.** Walking the C2 baseline Land set asserts each
    still admits; Mirrorpool's FLIP is the only delta.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    printings = OracleParserCardSource().get_printings()
    for name in PHASE_1_3_4D_4B_ADMITTED_LAND_CARRIERS:
        assert name in printings, f"verify-first: {name} missing from pool"
        assert _printing_is_bridge_simple_carrier_aa_land(printings[name]), (
            f"Phase 4B C4 invariant: {name} must STILL admit on the "
            f"Land predicate post-C4 (no regression)."
        )


def test_phase_4d_artifact_admit_set_unchanged_post_phase_4b_c4():
    """**Phase 4B C4 no-regression pin — the Artifact admit set stays
    intact post-C4** (C4 is Land-focused via Mirrorpool — Artifact
    siblings are untouched).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    printings = OracleParserCardSource().get_printings()
    for name in PHASE_4D_ADMITTED_ARTIFACT_CARRIERS:
        assert name in printings, f"verify-first: {name} missing from pool"
        assert _printing_is_bridge_simple_carrier_aa_artifact(
            printings[name],
        ), (
            f"Phase 4B C4 invariant: {name} must STILL admit on the "
            f"Artifact predicate post-C4 (no regression)."
        )
