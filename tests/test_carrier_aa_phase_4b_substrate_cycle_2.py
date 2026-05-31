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
    """**Phase 4B C4 inversion — Mirrorpool's per-AA walk now admits
    BOTH (was 1 admit + 1 decline pre-C4).**

    Pre-C4 (post-C2): AA[0] declined on the missing Effect-class widen.
    Post-C4: AA[0]'s Effect class
    ``CopyTargetInstantOrSorceryYouControl`` is in the admit set
    (Phase 4B C4 widen); AA[1] continues to admit (Phase 4B C2 widen).
    Both per-AA gates pass — Mirrorpool FLIPs at the multi-AA
    all-or-nothing gate.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    printing = OracleParserCardSource().get_printings()["Mirrorpool"]
    assert len(printing.activated_abilities) == 2
    aa0 = printing.activated_abilities[0]
    aa1 = printing.activated_abilities[1]
    # **Phase 4B C4 inversion (2026-05-26).** AA[0] now ADMITS.
    assert _aa_is_phase1_sub_shape_a(aa0), (
        "Phase 4B C4 inversion: Mirrorpool AA[0] (CopyTargetInstantOr"
        "SorceryYouControl) FLIPS ADMITTED at the per-AA admit "
        "predicate post-C4 — the C4 widen lands its Effect class in "
        "``_carrier_aa_phase_1_effect_classes``."
    )
    assert _aa_is_phase1_sub_shape_a(aa1), (
        "Phase 4B C2 invariant: Mirrorpool AA[1] (CreateTokenCopyOf"
        "TargetCreatureYouControl) ADMITS at the per-AA admit "
        "predicate (C2 widen at ``58988ade``)."
    )


def test_mirrorpool_printing_level_admit_stays_declined_post_c2():
    """**Phase 4B C4 inversion — Mirrorpool's PRINTING-level admit
    FLIPs ADMITTED post-C4 (was DECLINED pre-C4).**

    Under the Phase 4A multi-AA all-or-nothing contract at
    :func:`_printing_is_bridge_simple_carrier_aa_land`, a printing
    admits only if EVERY AA admits. Post-C4 both AAs admit (per the
    C2 widen for AA[1] and the C4 widen for AA[0]) — Mirrorpool's
    printing-level admit FLIPs at the Land predicate AND the unified
    dispatcher.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    printing = OracleParserCardSource().get_printings()["Mirrorpool"]
    # **Phase 4B C4 inversion (2026-05-26).** FLIPs ADMITTED on the
    # Land predicate.
    assert _printing_is_bridge_simple_carrier_aa_land(printing), (
        "Phase 4B C4 invariant: Mirrorpool FLIPs ADMITTED on the Land "
        "predicate post-C4 — both per-AA Effect classes admit; the "
        "multi-AA all-or-nothing gate passes."
    )
    # Mirrorpool is Land-typed, not Artifact — Artifact predicate
    # still declines on the card_type guard.
    assert not _printing_is_bridge_simple_carrier_aa_artifact(printing), (
        "Phase 4B C2 invariant: Mirrorpool declines on the Artifact "
        "sibling predicate (it's Land-typed, not Artifact)."
    )
    # **Phase 4B C4 inversion (2026-05-26).** FLIPs ADMITTED on the
    # unified dispatcher (the Land path admits).
    assert _printing_is_bridge_simple_carrier_aa_any(printing), (
        "Phase 4B C4 invariant: Mirrorpool FLIPs ADMITTED on the "
        "unified admit dispatcher post-C4 — the Land sibling admits."
    )


# ---------------------------------------------------------------------------
# C2 admit-set sentinel — partial widen contract
# ---------------------------------------------------------------------------


def test_phase_4b_c2_admit_set_widened_by_exactly_one():
    """**Phase 4B C2 sentinel — INVERTED at C4 for the full FLIP.**

    Originally pinned the C2-Option-A partial widen contract (admit set
    grows by exactly 1, AA[1]'s class in, AA[0]'s class out). The C4
    full FLIP (commit lands the AA[0] Python admit widen + bridge
    arms + Mirrorpool FLIP) adds AA[0]'s
    ``CopyTargetInstantOrSorceryYouControl`` to the admit set — so the
    expected set bumps to 15 classes and the AA[0] honest-stop check
    inverts to an in-admit-set assertion.

    Naming kept stable (no rename to ``_post_c4``) — the snapshot
    semantics drift forward with each cycle's widen; cross-referencing
    test failure logs to commit history makes the audit trail.
    """
    from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.effects.generic.damage import (
        DealDamageToControllerAndAddMana,
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
    from mtg_bot.effects.generic.life import GrantLifeToEachOpponent
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
        AddManaToPool,
        AddNManaOfChosenColor,
        AddOneManaFromControlledLandsProductions,
        AddOneManaOfChosenPermanentColor,
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
    # Expected post-C4 admit set (post-rebase-onto-Spacecraft-P4-C2 +
    # post-Meteor-Crater-P4-C2 + post-Reflecting-Pool-P4-C2 +
    # post-Ancient-Tomb-P4-C2):
    # Phase 1-3 (7) + Phase 4C C2 (2) + Phase 4D C2 (2) + Phase 4E C2
    # (2) + Phase 4B C2 (1) + Spacecraft P4 C2 (1) + Phase 4B C4
    # (1) + Meteor Crater P4 C2 (1) + Reflecting Pool P4 C2 (1) +
    # Ancient Tomb P4 C2 (1) = 19.
    expected_post_c4 = frozenset({
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
        # Phase 4B C2:
        CreateTokenCopyOfTargetCreatureYouControl,
        # Spacecraft Phase 4 C2 (rebase pickup):
        AddChargeCounterManaOfChosenColor,
        # Phase 4B C4:
        CopyTargetInstantOrSorceryYouControl,
        # Meteor Crater Phase 4 C2:
        AddOneManaOfChosenPermanentColor,
        # Reflecting Pool Phase 4 C2:
        AddOneManaFromControlledLandsProductions,
        # Ancient Tomb Phase 4 C2:
        DealDamageToControllerAndAddMana,
        # Grove of the Burnwillows (2026-05-31) -- the two Sequence
        # leaf classes (the Sequence-IN-AA admit closure):
        AddNManaOfChosenColor,
        GrantLifeToEachOpponent,
    })
    assert admit_set == expected_post_c4, (
        "Grove admit set sentinel: post-C4 + post-Meteor-Crater-"
        f"C2 + post-Reflecting-Pool-C2 + post-Ancient-Tomb-C2 + Grove "
        f"admit set must be the 21-class set; got {len(admit_set)} "
        f"classes, delta = added {admit_set - expected_post_c4} / "
        f"missing {expected_post_c4 - admit_set}"
    )
    # **Phase 4B C4 inversion (2026-05-26).** AA[0]'s class IS in the
    # admit set post-C4 (the full FLIP). Was NOT-IN pre-C4 per the
    # Option A honest-stop.
    assert CopyTargetInstantOrSorceryYouControl in admit_set, (
        "Phase 4B C4 invariant: CopyTargetInstantOrSorceryYouControl "
        "must BE in _carrier_aa_phase_1_effect_classes post-C4 (the "
        "AA[0] Python admit widen + bridge arms ship together with "
        "the Mirrorpool FLIP at C4; the C3 Rust substrate at "
        "``e5cd1c18`` was the immediate predecessor)."
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
    """**Phase 4B C2 invariant — Phase-1-3 Land admit set stays
    intact + grows by Mirrorpool at C4.**

    Pre-C4 this walked the 7-card baseline (Mirrorpool DECLINED on
    AA[0]'s teeth). Post-C4 the AA[0] half admits and Mirrorpool
    FLIPS — so the walk now confirms the 7-card baseline stays
    admitted AND Mirrorpool is freshly admitted via the C4 widen.
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
    # **Phase 4B C4 (2026-05-26).** Mirrorpool FLIPS DECLINED →
    # ADMITTED via the full Option A FLIP at C4.
    assert "Mirrorpool" in printings, (
        "verify-first: Mirrorpool missing from pool"
    )
    assert _printing_is_bridge_simple_carrier_aa_land(
        printings["Mirrorpool"],
    ), (
        "Phase 4B C4 invariant: Mirrorpool must FLIP ADMITTED on the "
        "Land predicate post-C4 (the AA[0] Python admit widen + bridge "
        "arms close the multi-AA all-or-nothing gate; C3 shipped the "
        "AA[0] Rust spell-copy substrate at ``e5cd1c18``)."
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
    """**Phase 4B C4 invariant — full-pool admit dispatcher walk.**

    Pre-C4 this asserted no silent auto-grow + Mirrorpool DECLINED.
    Post-C4 the dispatcher admits the C2 baseline PLUS Mirrorpool —
    the full pool admit set grows by exactly 1 (Mirrorpool's FLIP).
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
        + PHASE_4D_ADMITTED_ARTIFACT_CARRIERS
        # **Phase 4B C4 (2026-05-26).** Mirrorpool FLIPS into the
        # full-pool admit set via the AA[0] Python admit widen +
        # bridge arms (C3 Rust substrate at ``e5cd1c18``).
        + ("Mirrorpool",)
        # **Meteor Crater Phase 4 C2 (2026-05-27).** Meteor Crater
        # FLIPS into the full-pool admit set via the Effect-class
        # widen for AddOneManaOfChosenPermanentColor (C1 Rust
        # substrate at ``eb059eaa``).
        + ("Meteor Crater",)
        # **Reflecting Pool Phase 4 C2 (2026-05-27).** Reflecting Pool
        # FLIPS into the full-pool admit set via the Effect-class
        # widen for AddOneManaFromControlledLandsProductions (C1 Rust
        # substrate at ``d7be074e``).
        + ("Reflecting Pool",)
        # **Ancient Tomb Phase 4 C2 (2026-05-27).** Ancient Tomb
        # FLIPS into the full-pool admit set via the Effect-class
        # widen for DealDamageToControllerAndAddMana (C1 Rust
        # substrate at ``c250a60d``).
        + ("Ancient Tomb",)
        # **Grove of the Burnwillows (2026-05-31).** Grove FLIPS into
        # the full-pool admit set via the Sequence-IN-AA admit + the
        # AddNManaOfChosenColor + GrantLifeToEachOpponent leaf-class
        # widens (new Rust Effect::GrantLifeToEachOpponent).
        + ("Grove of the Burnwillows",),
    )
    assert admitted == expected, (
        f"Phase 4B C4 + Meteor Crater C2 + Reflecting Pool C2 + "
        f"Ancient Tomb C2 + Grove invariant: full-pool admit set must "
        f"be exactly the C2 baseline + Mirrorpool + Meteor Crater + "
        f"Reflecting Pool + Ancient Tomb + Grove; got admit delta = "
        f"added {admitted - expected} / missing {expected - admitted}"
    )
    # **Phase 4B C4 inversion (2026-05-26).** Mirrorpool MUST appear
    # in the admit set post-C4 (was DECLINED pre-C4).
    assert "Mirrorpool" in admitted, (
        "Phase 4B C4 FLIP: Mirrorpool must be in the printing-level "
        "admit dispatcher post-C4 (both per-AA Effect classes now "
        "admit; multi-AA all-or-nothing gate flips)."
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
    """**Phase 4B C4 inversion — AA[0]'s bridge forward arm FLIPs
    ADMITTED post-C4.**

    Pre-C4 (post-C2): the C2 widen lived in :mod:`trajectory` only;
    :func:`_python_aa_to_safe_dict` had no recognizer for AA[0]'s
    Effect class so the forward arm honest-declined.

    Post-C4: the C4 widen lands the recognizer + reverse arm + admit
    widen together — the forward arm emits a non-None dict.
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
    # **Phase 4B C4 inversion (2026-05-26).**
    assert d is not None, (
        "Phase 4B C4 invariant: AA[0]'s bridge forward arm FLIPs "
        "ADMITTED post-C4 (the recognizer + reverse arm + admit "
        "widen all land at C4)."
    )
    assert d["effect"] == {
        "kind": "copy_target_instant_or_sorcery_you_control",
    }


# ---------------------------------------------------------------------------
# C2 live Mirrorpool round-trip — confirms the partial state via real parser
# ---------------------------------------------------------------------------


def test_mirrorpool_live_per_aa_dict_partial_round_trip_post_c2():
    """**Phase 4B C4 inversion — both Mirrorpool AAs round-trip post-
    C4.**

    Pre-C4 (post-C2): AA[0] honest-declined at the bridge floor (no
    recognizer); AA[1] succeeded. The C4 widen adds the AA[0]
    recognizer + reverse arm; both AAs now emit non-None dicts.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    printing = OracleParserCardSource().get_printings()["Mirrorpool"]
    assert len(printing.activated_abilities) == 2

    aa0_dict = _python_aa_to_safe_dict(printing.activated_abilities[0])
    aa1_dict = _python_aa_to_safe_dict(printing.activated_abilities[1])

    # **Phase 4B C4 inversion (2026-05-26).** AA[0] emits non-None.
    assert aa0_dict is not None, (
        "Phase 4B C4 invariant: Mirrorpool AA[0]'s bridge forward arm "
        "FLIPs ADMITTED post-C4."
    )
    assert aa0_dict["effect"] == {
        "kind": "copy_target_instant_or_sorcery_you_control",
    }
    assert aa1_dict is not None, (
        "Phase 4B C2 invariant: Mirrorpool AA[1]'s bridge forward arm "
        "emits a non-None dict (C1 forward arm)."
    )
    assert aa1_dict["effect"] == {
        "kind": "create_token_copy_of_target_creature_you_control",
    }
