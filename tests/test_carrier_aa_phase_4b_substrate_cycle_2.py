"""**Carrier-AA substrate Phase 4B Cycle 2 (2026-05-26 — Option A
partial widen per design doc §3B / §5.4 / §7.2).**

The C1 substrate at ``434d6aa1`` (rebased + merged via ``818b4c64``)
shipped the Rust slice for Mirrorpool's AA[1]
(``CreateTokenCopyOfTargetCreatureYouControl``, CR-707.5 token-
creature-copy): activator-bf Creature target fan-out in
``state_ops_legal.rs::activate_ability_dict``, target validation in
``state_ops_actions.rs::ActivateAbility``, target-aware resolve in
``state_ops_resolve.rs`` (consults
``current_resolve_payload_target_id`` FIRST, falls back to the
deterministic-first scan), forward arm in
``cross_engine.py::_python_aa_to_safe_dict``, and the pre-existing
reverse arm at ``cross_engine.py:7190``. C2 widens the Python admit
set to flip AA[1]'s per-AA admit predicate gate from DECLINED →
ADMITTED.

**Cycle 2 is OPTION A (partial widen + honest-stop).** The sibling
AA[0] ``CopyTargetInstantOrSorceryYouControl`` (CR-707.2 spell-copy)
has NO Rust substrate at C2 — the new ``Effect`` variant + parse +
to_pydict + resolve arm (push copy of spell onto stack with activator
as controller per CR 707.2) + ``StackItem.is_copy`` audit + new
stack-target fan-out in ``state_ops_legal.rs`` all defer to a future
Rust cycle per design doc §4.1.1. Under the Phase 4A multi-AA all-
or-nothing contract, Mirrorpool's printing-level admit STAYS DECLINED
post-C2 because AA[0] bites on the per-AA Effect-class teeth (its
class is intentionally NOT widened here — the cross-engine bridge
floor would honest-decline anyway since there's no forward arm).

**The full Mirrorpool DECLINED → ADMITTED FLIP defers to a follow-up
sequence:**

  * C3 (Rust agent): ``Effect::CopyTargetInstantOrSorceryYouControl``
    variant + parse / resolve / to_pydict arms + stack-target fan-out
    + ``StackItem.is_copy`` audit + 5 Rust unit pins per §6.2 #9-13.
  * C4 (Python/bridge agent): Effect-class widen
    ``CopyTargetInstantOrSorceryYouControl`` + forward arm in
    ``_python_aa_to_safe_dict`` + reverse arm in
    ``_ta_dict_to_python_effect`` + Mirrorpool FLIP DECLINED →
    ADMITTED + walk inversion in
    ``tests/test_carrier_aa_phase_4a_substrate_cycle_1.py``
    (Mirrorpool moves OUT of ``PHASE_4_DECLINED_CARRIERS``).
  * C5 (Python agent): real-EoE per-card probe — AA[0] spell-copy
    line + AA[1] token-copy line per design doc §6.7.

Test pins ship per design doc §6.2 #5-8 / §7.2 row C3 (the Python
admit + FLIP cycle, narrowed to AA[1]'s half at C2 per Option A):

  5. (Already in C1 file at ``test_python_create_token_copy_of_
     target_creature_class_exists`` + ``test_mirrorpool_live_aa_
     shapes_match_design_doc``) -- parser SoT pin for the
     ``CreateTokenCopyOfTargetCreatureYouControl`` Python class +
     Mirrorpool live AA[0]/AA[1] shapes.
  6. (Already in C1 file at ``test_bridge_forward_arm_create_token_
     copy_bare`` + ``test_bridge_forward_arm_create_token_copy_with_
     additional_subtype_declines`` + ``test_bridge_round_trip_
     create_token_copy_bare``) -- bridge round-trip pins for AA[1]'s
     Effect class.
  7. (Already in C1 file at ``test_mirrorpool_stays_declined_at_
     admit_gate_post_c2`` — RENAMED + INVERTED per C2 contract).
  8. NEW IN C2: admit-now-passes-AA[1]-post-C2 inversion pins (per-AA
     predicate FLIP + printing-level honest-stop).

Plus C2-specific sentinel pins:

  * The Effect-class admit set widened by exactly 1 (token-copy in,
    spell-copy out) — sibling of the C1 ``test_create_token_copy_
    effect_class_admit_set_post_c2`` pin in the C1 file.
  * Mirrorpool's per-AA walk now mixes 1 admit + 1 decline (AA[1]
    flips, AA[0] stays).
  * The printing-level admit (Land / Artifact / unified dispatcher)
    STAYS DECLINED on AA[0]'s teeth.
  * Pool-parity invariant: the Phase-3 admit set (Swarmyard /
    Deserted Temple / Petrified Field / Terrain Generator /
    Mystifying Maze / Scavenger Grounds / Thespian's Stage) +
    Phase-4D admit (Keys to the House) STAYS UNCHANGED post-C2 — no
    silent auto-grow at the printing-level admit set.

ZERO Rust changes this cycle (the C1 Rust substrate at ``434d6aa1``
covers AA[1]'s entire Rust surface). ZERO bridge-arm changes
(forward + reverse arms shipped C1).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# C2 admit-gate FLIP — AA[1]'s per-AA predicate inverts DECLINED -> ADMITTED
# ---------------------------------------------------------------------------


def test_create_token_copy_aa_admits_at_per_aa_predicate_post_c2():
    """**Phase 4B C2 per-AA admit FLIP — AA[1] now ADMITS.** A
    synthetic AA shaped like Mirrorpool's AA[1] (bare
    ``{N}, {T}, Sac`` cost + ``CreateTokenCopyOfTargetCreatureYou
    Control()`` effect) passes :func:`_aa_is_phase1_sub_shape_a`
    post-C2 widen.

    Pre-C2 invariant (asserted at the C1 file's
    ``test_mirrorpool_stays_declined_at_admit_gate_post_c1`` pin —
    renamed and inverted to ``_post_c2``): AA[1] declined on the
    Effect-class teeth. Post-C2: admits.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=5),
        ),
        effect=CreateTokenCopyOfTargetCreatureYouControl(),
    )
    assert _aa_is_phase1_sub_shape_a(aa), (
        "Phase 4B C2 inversion: a synthetic AA shaped like Mirrorpool's "
        "AA[1] (bare {N},{T},Sac + CreateTokenCopyOfTargetCreatureYou"
        "Control()) MUST admit at the per-AA predicate post-C2 widen "
        "of _carrier_aa_phase_1_effect_classes"
    )


def test_create_token_copy_aa_with_subtype_rider_still_declines_at_bridge():
    """**Phase 4B C2 honest-decline preserved on the
    ``additional_subtype`` rider.** The per-AA predicate
    :func:`_aa_is_phase1_sub_shape_a` does NOT inspect the
    ``additional_subtype`` rider — the Effect-class gate admits the
    class regardless of its data payload. The honest-decline lives at
    the cross-engine bridge floor
    :func:`cross_engine._python_aa_to_safe_dict` instead.

    So an AA with ``additional_subtype="Reflection"`` (the Mirror
    Room shape per design doc §3.10) passes the per-AA admit but
    honest-declines at the bridge — Rust's
    ``Effect::CreateTokenCopyOfTargetCreatureYouControl`` is unit and
    can't carry the rider, so the round-trip would lose information
    silently. The decline is intentional and lives at the bridge,
    not the per-AA predicate.

    Mirrorpool's live AA[1] is ``additional_subtype=None`` so this
    decline path is unreachable from production today.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=5),
        ),
        effect=CreateTokenCopyOfTargetCreatureYouControl(
            additional_subtype="Reflection",
        ),
    )
    # Per-AA predicate ADMITS — the predicate doesn't inspect rider data.
    assert _aa_is_phase1_sub_shape_a(aa), (
        "Phase 4B C2 invariant: the per-AA predicate does NOT inspect "
        "the additional_subtype rider; admit is based on Effect class "
        "only. The rider-aware honest-decline lives at the cross-engine "
        "bridge floor."
    )
    # Bridge floor HONEST-DECLINES on the rider.
    assert _python_aa_to_safe_dict(aa) is None, (
        "Phase 4B C2 invariant: the bridge forward arm must honest-"
        "decline a CreateTokenCopyOfTargetCreatureYouControl with "
        "additional_subtype != None (Rust's variant is unit; the rider "
        "is not representable on the wire). This decline path is "
        "unreachable from Mirrorpool's live AA[1] (additional_subtype="
        "None) — Mirror Room would be the live consumer."
    )


# ---------------------------------------------------------------------------
# C2 honest-stop — Mirrorpool STAYS DECLINED at the printing-level admit
# ---------------------------------------------------------------------------


def test_mirrorpool_live_per_aa_mixed_admit_decline_post_c2():
    """**Phase 4B C2 honest-stop pin — Mirrorpool's per-AA walk mixes
    1 admit + 1 decline post-C2 (Option A partial widen).**

    AA[0] ``CopyTargetInstantOrSorceryYouControl`` STAYS DECLINED at
    the per-AA admit predicate (its Effect class is intentionally NOT
    in ``_carrier_aa_phase_1_effect_classes`` at C2 — the AA[0] Rust
    substrate defers to a future cycle).

    AA[1] ``CreateTokenCopyOfTargetCreatureYouControl`` FLIPS ADMITTED
    at the per-AA admit predicate (C2 widens the admit set to include
    the class).

    Sibling of the C1 file's ``test_mirrorpool_stays_declined_at_
    admit_gate_post_c2`` pin (which asserts the same per-AA mix +
    the printing-level admit stays declined).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    printing = OracleParserCardSource().get_printings()["Mirrorpool"]
    assert len(printing.activated_abilities) == 2
    aa0 = printing.activated_abilities[0]
    aa1 = printing.activated_abilities[1]
    assert not _aa_is_phase1_sub_shape_a(aa0), (
        "Phase 4B C2 invariant: Mirrorpool AA[0] (CopyTargetInstantOr"
        "SorceryYouControl) STAYS DECLINED at the per-AA admit "
        "predicate post-Cycle-2 — its Effect class is intentionally "
        "NOT widened (Rust substrate defers to a future cycle per "
        "design doc §4.1.1)"
    )
    assert _aa_is_phase1_sub_shape_a(aa1), (
        "Phase 4B C2 inversion: Mirrorpool AA[1] (CreateTokenCopyOf"
        "TargetCreatureYouControl) FLIPS ADMITTED at the per-AA admit "
        "predicate post-Cycle-2 — its Effect class is widened by C2"
    )


def test_mirrorpool_printing_level_admit_stays_declined_post_c2():
    """**Phase 4B C2 honest-stop pin — Mirrorpool's PRINTING-level
    admit STAYS DECLINED post-C2 (multi-AA all-or-nothing).**

    Under the Phase 4A multi-AA all-or-nothing contract at
    :func:`_printing_is_bridge_simple_carrier_aa_land`, a printing
    admits only if EVERY AA admits. Mirrorpool's AA[0] stays declined
    (per-AA Effect-class teeth), so the printing-level admit STAYS
    DECLINED on AA[0]'s teeth alone — that's Option A's honest-stop.

    The full FLIP DECLINED → ADMITTED requires the AA[0] Rust cycle
    + a follow-up Python widen + bridge arms (refined Phase 4B
    sequencing in trajectory.py docstring + worklog).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    printing = OracleParserCardSource().get_printings()["Mirrorpool"]
    assert not _printing_is_bridge_simple_carrier_aa_land(printing), (
        "Phase 4B C2 invariant: Mirrorpool STAYS DECLINED on the Land "
        "predicate post-Cycle-2 — AA[0]'s untouched Effect-class teeth "
        "bite under the multi-AA all-or-nothing contract"
    )
    # Mirrorpool is Land-typed, not Artifact — confirm the Artifact
    # predicate also declines (cleanly, on the card_type guard).
    assert not _printing_is_bridge_simple_carrier_aa_artifact(printing), (
        "Phase 4B C2 invariant: Mirrorpool declines on the Artifact "
        "sibling predicate (it's Land-typed, not Artifact)"
    )
    assert not _printing_is_bridge_simple_carrier_aa_any(printing), (
        "Phase 4B C2 invariant: Mirrorpool STAYS DECLINED on the "
        "unified admit dispatcher post-Cycle-2 — neither sibling "
        "admits"
    )


# ---------------------------------------------------------------------------
# C2 admit-set sentinel — partial widen contract
# ---------------------------------------------------------------------------


def test_phase_4b_c2_admit_set_widened_by_exactly_one():
    """**Phase 4B C2 sentinel — the Effect-class admit set grows by
    exactly 1 (AA[1]'s class in, AA[0]'s class out).** Option A's
    partial-widen contract.

    Sibling of the renamed C1-file pin
    ``test_create_token_copy_effect_class_admit_set_post_c2``; this
    pin adds the explicit "exactly one new class" assertion + the
    full pre/post delta walk.
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
    from mtg_bot.effects.generic.mana import AddManaToPool
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
    # Expected post-C2 admit set: Phase 1-3 (7) + Phase 4C C2 (2) +
    # Phase 4D C2 (2) + Phase 4E C2 (2) + Phase 4B C2 (1) = 14.
    expected_post_c2 = frozenset({
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
        # Phase 4E C2:
        DrawCardsByConditionMultiplier,
        AddManaToPool,
        # Phase 4C C2:
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
        # Phase 4D C2:
        LockOrUnlockDoorOfTargetRoomYouControl,
        SearchLibraryForCard,
        # Phase 4B C2 (the new one):
        CreateTokenCopyOfTargetCreatureYouControl,
    })
    assert admit_set == expected_post_c2, (
        "Phase 4B C2 admit set sentinel: post-C2 admit set must be "
        f"the 14-class set; got {len(admit_set)} classes, delta = "
        f"added {admit_set - expected_post_c2} / "
        f"missing {expected_post_c2 - admit_set}"
    )
    # Option A honest-stop: AA[0]'s class is intentionally NOT in.
    assert CopyTargetInstantOrSorceryYouControl not in admit_set, (
        "Phase 4B C2 Option A honest-stop: CopyTargetInstantOrSorcery"
        "YouControl must NOT be in _carrier_aa_phase_1_effect_classes "
        "at C2 (Rust substrate defers to a future cycle per design "
        "doc §4.1.1)"
    )


# ---------------------------------------------------------------------------
# C2 admit-set pool-parity — no silent auto-grow at the printing-level admit
# ---------------------------------------------------------------------------


PHASE_1_3_4D_ADMITTED_LAND_CARRIERS = (
    "Swarmyard",         # Phase 1
    "Deserted Temple",   # Phase 1.5a
    "Petrified Field",   # Phase 2a
    "Terrain Generator", # Phase 2b
    "Mystifying Maze",   # Phase 3A
    "Scavenger Grounds", # Phase 3B
    "Thespian's Stage",  # Phase 3C
    # Additional Lands admitted via Effect-class widens for Phase 4C/4D/4E
    # (sibling-admit spillover -- these carry a single AA with an
    # Effect-class that's in the post-4C/4D/4E admit set; the Phase-4B
    # C2 widen does not change this set).
    "Crystal Quarry",    # Phase-4C/4D/4E spillover -- AddManaToPool sibling
    "Eldrazi Temple",    # Phase-4C/4D/4E spillover -- AddManaToPool sibling
    "Gemstone Caverns",  # Phase-4C/4D/4E spillover -- AddManaToPool sibling
    "Sunken Citadel",    # Phase-4C/4D/4E spillover -- AddManaToPool sibling
)

PHASE_4D_ADMITTED_ARTIFACT_CARRIERS = (
    "Keys to the House",  # Phase 4D
    # Additional Artifacts admitted via Phase 4C / 4E widens.
    "Ghost Vacuum",       # Phase 4C
    "All-Fates Scroll",   # Phase 4E C2 partial-FLIP
)


def test_phase_1_3_4d_land_admit_set_unchanged_post_phase_4b_c2():
    """**Phase 4B C2 invariant — the 7-card Phase-1-3 Land admit set
    stays UNCHANGED post-Cycle-2.** Confirms Option A's partial
    widen does NOT auto-grow the printing-level admit set on the
    Land predicate side. Mirrorpool stays DECLINED on AA[0]'s teeth.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    printings = OracleParserCardSource().get_printings()
    for name in PHASE_1_3_4D_ADMITTED_LAND_CARRIERS:
        assert name in printings, f"verify-first: {name} missing from pool"
        assert _printing_is_bridge_simple_carrier_aa_land(printings[name]), (
            f"Phase 4B C2 invariant: {name} must STAY admitted on the "
            f"Land predicate post-Cycle-2 (Option A widen is on the "
            f"per-AA Effect-class gate, not the printing-level admit)"
        )


def test_phase_4d_artifact_admit_set_unchanged_post_phase_4b_c2():
    """**Phase 4B C2 invariant — Keys to the House (the sole pre-4B
    Phase-4D Artifact admit) stays ADMITTED post-Cycle-2.** Confirms
    Option A's partial widen does NOT regress the Artifact sibling
    admit set.
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
            f"Phase 4B C2 invariant: {name} must STAY admitted on the "
            f"Artifact predicate post-Cycle-2"
        )


def test_full_pool_admit_set_unchanged_post_phase_4b_c2():
    """**Phase 4B C2 invariant — no silent auto-grow.** Walk the FULL
    EoE pool and assert the unified admit dispatcher
    :func:`_printing_is_bridge_simple_carrier_aa_any` returns the
    EXACT same admit set as the named expected set (7 Lands + 1
    Artifact = 8 cards). No new card silently admits via the C2
    widen.
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
        PHASE_1_3_4D_ADMITTED_LAND_CARRIERS
        + PHASE_4D_ADMITTED_ARTIFACT_CARRIERS,
    )
    assert admitted == expected, (
        f"Phase 4B C2 invariant: full-pool admit set must be exactly "
        f"the 8-card Phase-1-3 + Phase-4D set; got admit delta = "
        f"added {admitted - expected} / missing {expected - admitted}"
    )
    # Mirrorpool MUST appear in the decline set (not in admitted).
    assert "Mirrorpool" not in admitted, (
        "Phase 4B C2 honest-stop: Mirrorpool must STAY DECLINED at the "
        "printing-level admit gate post-Cycle-2 (AA[0]'s untouched "
        "Effect-class teeth bite under the multi-AA all-or-nothing "
        "contract)"
    )


# ---------------------------------------------------------------------------
# C2 bridge-arm sanity — AA[1]'s forward emit + reverse arm still work
# ---------------------------------------------------------------------------


def test_aa1_bridge_forward_emit_still_works_post_c2():
    """**Phase 4B C2 sanity — AA[1]'s bridge forward arm (shipped C1)
    still produces a non-None dict post-C2 widen.** The C2 widen
    is in :func:`_carrier_aa_phase_1_effect_classes` only; the
    cross-engine bridge floor :func:`_python_aa_to_safe_dict` was
    NOT changed in C2.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=5),
        ),
        effect=CreateTokenCopyOfTargetCreatureYouControl(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Phase 4B C2 sanity: AA[1]'s bridge forward arm (shipped C1) "
        "must still produce a non-None dict post-C2 widen"
    )
    assert d["effect"] == {
        "kind": "create_token_copy_of_target_creature_you_control",
    }


def test_aa0_bridge_forward_still_honest_declines_post_c2():
    """**Phase 4B C2 honest-stop sanity — AA[0]'s bridge forward arm
    still honest-declines (returns None) post-C2.** The C2 widen
    does NOT touch the cross-engine bridge floor's recognizer set;
    :func:`_python_aa_to_safe_dict` still has no recognizer for
    ``CopyTargetInstantOrSorceryYouControl`` so the forward arm
    falls through to the ``effect_dict is None`` decline.

    Sibling-of-design-doc-§5.4 spec: the C4 future cycle ships the
    recognizer + reverse arm + admit widen together.
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
            mana=ManaCost(generic=3),  # Mirrorpool AA[0]'s {2}{C} = 3 generic
        ),
        effect=CopyTargetInstantOrSorceryYouControl(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is None, (
        "Phase 4B C2 honest-stop sanity: AA[0]'s bridge forward arm "
        "must still honest-decline (return None) post-C2 — no "
        "recognizer for CopyTargetInstantOrSorceryYouControl exists "
        "yet (C4 future cycle ships it together with the AA[0] Rust "
        "substrate)"
    )


# ---------------------------------------------------------------------------
# C2 live Mirrorpool round-trip — confirms the partial state via real parser
# ---------------------------------------------------------------------------


def test_mirrorpool_live_per_aa_dict_partial_round_trip_post_c2():
    """**Phase 4B C2 live round-trip — Mirrorpool's two AAs each
    serialize through ``_python_aa_to_safe_dict`` independently
    post-C2.** AA[0] honest-declines (no recognizer); AA[1] succeeds
    (recognizer + admit set widened).

    Same shape as the C1 file's
    ``test_mirrorpool_two_aa_list_round_trip_partial_at_c1`` pin —
    the C1 + C2 state of the bridge floor is identical (the C2
    widen lives in :mod:`mtg_bot.parity.trajectory` only).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    printing = OracleParserCardSource().get_printings()["Mirrorpool"]
    assert len(printing.activated_abilities) == 2

    aa0_dict = _python_aa_to_safe_dict(printing.activated_abilities[0])
    aa1_dict = _python_aa_to_safe_dict(printing.activated_abilities[1])

    assert aa0_dict is None, (
        "Phase 4B C2 invariant: Mirrorpool AA[0] (CopyTargetInstantOr"
        "SorceryYouControl) bridge forward arm must still honest-"
        "decline post-Cycle-2 (no recognizer; Rust variant doesn't "
        "exist)"
    )
    assert aa1_dict is not None, (
        "Phase 4B C2 invariant: Mirrorpool AA[1] (CreateTokenCopyOf"
        "TargetCreatureYouControl, additional_subtype=None) bridge "
        "forward arm continues to succeed post-Cycle-2"
    )
    assert aa1_dict["effect"] == {
        "kind": "create_token_copy_of_target_creature_you_control",
    }
