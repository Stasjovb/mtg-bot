"""**Carrier-AA substrate Phase 4C Cycle 2 (2026-05-26) — Ghost Vacuum FLIP.**

Tests for the Phase 4C Cycle 2 Python admit widen + Rust sorcery_speed
slot + Ghost Vacuum admit-gate FLIP per
``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.5 (Python bridge
spec) + §6.3 (test plan, pins #14-17, #23) + §7.3 (cycle plan).

Cycle 2 deliverables:

  - **Rust slot.** ``ActivatedAbility`` struct (``rust/src/cards.rs``
    around line 11091) gains a ``sorcery_speed: bool`` field;
    ``parse_activated_ability`` reads the optional ``sorcery_speed``
    key from the registry dict (defaults ``false`` when absent —
    back-compat with every pre-C2 caller). DATA-CARRYING ONLY at
    this slice — the activation-time legality gate (CR 605.3a
    sorcery-timing block) defers to a follow-up cycle; see
    ``docs/SEARCH_LIMITATIONS.md`` Phase 4C entry.
  - **Effect-class admit-set widen** (9 → 11): adds
    ``ExileTargetCardFromGraveyard`` (Ghost Vacuum AA[0] pilot) +
    ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
    Control`` (Ghost Vacuum AA[1] recall pilot — riders data-
    carrying only at Rust today; the layered-grant flying-counter
    + Spirit-overlay defers to Phase N).
  - **AA-rider gate widen**:
    :func:`cross_engine._python_aa_to_safe_dict` lifts the
    ``aa.sorcery_speed: return None`` decline arm at line 14798; the
    AA dict emit at the bottom of the function emits
    ``"sorcery_speed": True`` when the rider is set.
  - **Reverse arm**:
    :func:`cross_engine._aa_dict_to_python_activated_ability` reads
    the optional ``sorcery_speed`` key from the AA dict and threads
    it onto the constructed ``ActivatedAbility`` (defaults False).
  - **Ghost Vacuum admit-gate FLIP**: DECLINED → ADMITTED at the
    production-deck admit gate (per-AA predicate passes both AAs;
    printing-level Artifact admit predicate passes; cross-engine
    builder gate emits a CardDef end-to-end).
  - **Phase-4A walk inversion**: Ghost Vacuum drops out of
    :data:`PHASE_4_DECLINED_CARRIERS` and into the admit invariant
    (mirror of Phase 4E C2's All-Fates Scroll partial-FLIP move).

**Test plan (per design doc §6.3 pins #14-17 + #23):**

  #14. Parser-SoT pin: Ghost Vacuum is parser-claimed by
       ``OracleParserCardSource`` with the exact 2-AA shape (AA[0]
       ``{T}: ExileTargetCardFromGraveyard``; AA[1] ``{6}, {T},
       Sacrifice this artifact: PutEach...; sorcery_speed=True;
       grant_flying_counter=True; grant_subtype_and_pt=('Spirit',
       1, 1)``).
  #15. Bridge round-trip pin: both AAs round-trip through
       ``_python_aa_to_safe_dict`` (+ reverse arm) byte-equal to
       the parsed ``ActivatedAbility`` instances.
  #16. Ghost Vacuum admit predicate inversion pin: live Ghost
       Vacuum printing PASSES
       ``_printing_is_bridge_simple_carrier_aa_artifact`` +
       ``_printing_is_bridge_simple_carrier_aa_any`` +
       ``_carrier_aa_artifact_card_def`` emits a CardDef.
  #17. Effect-class admit-set widen pin: frozenset grows 9 → 11
       with the two new entries; the 9 prior entries stay admitted
       (no regression).
  #23. ``sorcery_speed`` AA-rider widen pin: a synthetic AA with
       ``sorcery_speed=True`` + a closed-vocab Effect (any of the
       11 admit-set entries) admits at the bridge floor; the AA
       dict carries ``"sorcery_speed": True``; the reverse arm
       reconstructs the AA byte-equal.

Plus negative-cases (other AA-riders still decline; the recall
variant's riders data-carry through the dict).
"""

from __future__ import annotations

import dataclasses
import json

import pytest


# ---------------------------------------------------------------------------
# §6.3 #17 — Effect-class admit-set widen
# ---------------------------------------------------------------------------


def test_phase_4c_c2_effect_class_widen_adds_two_entries():
    """**§6.3 #17.** ``_carrier_aa_phase_1_effect_classes`` grows from
    9 → 11 entries at Phase 4C C2 (Ghost Vacuum's two AA Effect
    classes). The 9 prior entries stay admitted (no regression).
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
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
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
    assert ExileTargetCardFromGraveyard in admitted
    assert (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl
        in admitted
    )
    # No regression -- the 9 prior entries stay.
    for cls in (
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
        DrawCardsByConditionMultiplier,
        AddManaToPool,
    ):
        assert cls in admitted, (
            f"Phase 4C C2 no-regression: {cls.__name__} dropped from "
            "the Effect-class admit set"
        )
    # Closed-set invariant (no silent auto-grow beyond the documented
    # +2 widens).
    assert len(admitted) == 11


# ---------------------------------------------------------------------------
# §6.3 #23 — AA-rider gate widen (sorcery_speed=True now admitted)
# ---------------------------------------------------------------------------


def test_phase_4c_c2_aa_rider_gate_admits_sorcery_speed():
    """**§6.3 #23 (predicate side).** A synthetic AA with
    ``sorcery_speed=True`` plus a closed-vocab admitted Effect passes
    :func:`_aa_is_phase1_sub_shape_a` (the sorcery_speed teeth is
    lifted).
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import ExileTargetCardFromGraveyard
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=ExileTargetCardFromGraveyard(),
        sorcery_speed=True,
    )
    assert _aa_is_phase1_sub_shape_a(aa) is True, (
        "Phase 4C C2 widen: a synthetic AA with sorcery_speed=True "
        "and a closed-vocab admitted Effect must PASS the per-AA "
        "admit gate (the sorcery_speed=True rider teeth is lifted)"
    )


def test_phase_4c_c2_aa_rider_gate_still_declines_activate_only_once():
    """**§6.3 #23 negative.** Lifting ``sorcery_speed`` doesn't
    silently lift the remaining AA-rider teeth — every other rider
    (activate_only_once, tier_threshold, room_half, cost_reductions)
    stays decline-only at this Phase. Defense-in-depth pin.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import ExileTargetCardFromGraveyard
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=ExileTargetCardFromGraveyard(),
        activate_only_once=True,  # The other AA-rider teeth
    )
    assert _aa_is_phase1_sub_shape_a(aa) is False, (
        "Phase 4C C2 widen is bounded -- activate_only_once=True "
        "still declines at the per-AA admit gate (Phase-N ships "
        "that widen)"
    )


def test_phase_4c_c2_sorcery_speed_rider_round_trips_through_bridge_floor():
    """**§6.3 #23 (round-trip side).** A synthetic AA with
    ``sorcery_speed=True`` + closed-vocab admitted Effect survives the
    bridge floor's forward arm: the dict carries
    ``sorcery_speed=True``; the reverse arm reconstructs the AA
    byte-equal.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import ExileTargetCardFromGraveyard
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=ExileTargetCardFromGraveyard(),
        sorcery_speed=True,
    )
    aa_dict = _python_aa_to_safe_dict(aa)
    assert aa_dict is not None, (
        "Synthetic AA with sorcery_speed=True + ExileTargetCardFromGraveyard "
        "Effect must round-trip cleanly (the sorcery_speed teeth is "
        "lifted at Phase 4C C2)"
    )
    assert aa_dict.get("sorcery_speed") is True, (
        "The sorcery_speed flag must propagate on the AA dict"
    )
    assert aa_dict["effect"]["kind"] == "exile_target_card_from_graveyard"
    # Reverse round-trip via _aa_dict_to_python_activated_ability.
    aa_back = _aa_dict_to_python_activated_ability(aa_dict)
    assert aa_back == aa, (
        "Reverse arm must reconstruct the AA byte-equal at the "
        "ActivatedAbility __eq__ surface"
    )


def test_phase_4c_c2_sorcery_speed_false_does_not_emit_flag():
    """**§6.3 #23 negative.** When ``sorcery_speed=False`` the AA dict
    must NOT carry the ``sorcery_speed`` key (empty-omit discipline,
    mirrors ``is_mana_ability``).
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=UntapTargetLand(),
        sorcery_speed=False,
    )
    aa_dict = _python_aa_to_safe_dict(aa)
    assert aa_dict is not None
    assert "sorcery_speed" not in aa_dict, (
        "sorcery_speed=False must not emit the key (empty-omit "
        "discipline mirrors is_mana_ability)"
    )


# ---------------------------------------------------------------------------
# §6.3 #14 — Parser-SoT pin (Ghost Vacuum live shape)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ghost_vacuum_printing():
    from mtg_bot.cards.parser_source import OracleParserCardSource
    printings = OracleParserCardSource().get_printings()
    return printings["Ghost Vacuum"]


def test_phase_4c_c2_ghost_vacuum_parser_claims_card(ghost_vacuum_printing):
    """**§6.3 #14.** Ghost Vacuum is parser-claimed with the exact 2-AA
    shape: AA[0] ``{T}: Exile target card from a graveyard.`` (unit
    Effect, no sorcery_speed); AA[1] ``{6}, {T}, Sacrifice this artifact:
    Put each creature card exiled... (sorcery_speed=True,
    grant_flying_counter=True, grant_subtype_and_pt=("Spirit", 1, 1))``.
    """
    from mtg_bot.effects.generic.exile import (
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )

    p = ghost_vacuum_printing
    assert p.card_types == ("Artifact",)
    assert p.subtypes == ()
    assert p.mana_cost.generic == 1
    assert not p.mana_cost.colored
    assert not p.mana_cost.x_pips
    aas = tuple(p.activated_abilities or ())
    assert len(aas) == 2
    # AA[0]
    aa0 = aas[0]
    assert isinstance(aa0.effect, ExileTargetCardFromGraveyard)
    assert aa0.cost.tap_self is True
    assert aa0.cost.sacrifice_self is False
    assert aa0.cost.mana is None
    assert aa0.sorcery_speed is False
    assert aa0.is_mana_ability is False
    # AA[1]
    aa1 = aas[1]
    assert isinstance(
        aa1.effect,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    assert aa1.cost.tap_self is True
    assert aa1.cost.sacrifice_self is True
    assert aa1.cost.mana is not None
    assert aa1.cost.mana.generic == 6
    assert aa1.sorcery_speed is True
    assert aa1.is_mana_ability is False
    # Recall variant rider payload.
    assert aa1.effect.grant_flying_counter is True
    assert aa1.effect.grant_subtype_and_pt == ("Spirit", 1, 1)


# ---------------------------------------------------------------------------
# §6.3 #15 — Bridge round-trip pin (Ghost Vacuum's two AAs)
# ---------------------------------------------------------------------------


def test_phase_4c_c2_ghost_vacuum_aa0_round_trips(ghost_vacuum_printing):
    """**§6.3 #15 (AA[0] side).** Ghost Vacuum AA[0]
    (ExileTargetCardFromGraveyard, tap_self only, no sorcery_speed)
    round-trips through the bridge floor; the reverse arm
    reconstructs the load-bearing AA fields byte-equal (mana_str
    display field excluded -- see sibling AA[1] pin).
    """
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa0 = ghost_vacuum_printing.activated_abilities[0]
    aa_dict = _python_aa_to_safe_dict(aa0)
    assert aa_dict is not None
    assert aa_dict["effect"]["kind"] == "exile_target_card_from_graveyard"
    assert "sorcery_speed" not in aa_dict  # empty-omit
    assert "is_mana_ability" not in aa_dict
    aa_back = _aa_dict_to_python_activated_ability(aa_dict)
    # AA[0] cost is empty-mana + tap_self only; AA[0] mana is None on
    # both sides so the bare dataclass __eq__ works (no mana_str
    # drift).
    assert aa_back == aa0


def test_phase_4c_c2_ghost_vacuum_aa1_round_trips(ghost_vacuum_printing):
    """**§6.3 #15 (AA[1] side).** Ghost Vacuum AA[1]
    (PutEachCreatureCardExiled..., mana=6, tap_self, sacrifice_self,
    sorcery_speed=True, recall rider payload) round-trips through the
    bridge floor; the reverse arm reconstructs the load-bearing AA
    fields byte-equal.

    Note on ``mana_str``: ``ActivationCost.mana_str`` is a parser-side
    display field (e.g. ``"{6}"``) that the bridge does NOT carry --
    only the structured ``mana: ManaCost`` field round-trips. The
    reverse arm reconstructs an ``ActivationCost`` with
    ``mana_str=""``; full-dataclass ``__eq__`` therefore drifts but
    every load-bearing field (mana, tap_self, sacrifice_self, etc.)
    is byte-equal.
    """
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa1 = ghost_vacuum_printing.activated_abilities[1]
    aa_dict = _python_aa_to_safe_dict(aa1)
    assert aa_dict is not None
    assert aa_dict["effect"]["kind"] == (
        "put_each_creature_card_exiled_with_source_"
        "onto_battlefield_under_your_control"
    )
    assert aa_dict["effect"].get("grant_flying_counter") is True
    sub_payload = aa_dict["effect"].get("grant_subtype_and_pt")
    assert sub_payload is not None
    sub, p_pt, t_pt = sub_payload
    assert (str(sub), int(p_pt), int(t_pt)) == ("Spirit", 1, 1)
    assert aa_dict.get("sorcery_speed") is True
    assert aa_dict["cost"]["tap_self"] is True
    assert aa_dict["cost"]["sacrifice_self"] is True
    assert aa_dict["cost"]["mana"] == {"generic": 6}
    aa_back = _aa_dict_to_python_activated_ability(aa_dict)
    # Load-bearing fields equal at the byte-level (mana_str excluded
    # per the docstring note; see the sibling Phase 4E C2 pin for the
    # same drift-tolerance discipline).
    assert aa_back.cost.mana == aa1.cost.mana
    assert aa_back.cost.tap_self == aa1.cost.tap_self
    assert aa_back.cost.sacrifice_self == aa1.cost.sacrifice_self
    assert aa_back.effect == aa1.effect
    assert aa_back.is_mana_ability == aa1.is_mana_ability
    assert aa_back.sorcery_speed == aa1.sorcery_speed
    assert aa_back.tier_threshold == aa1.tier_threshold
    assert aa_back.activate_only_once == aa1.activate_only_once
    assert aa_back.cost_reductions == aa1.cost_reductions
    assert aa_back.room_half == aa1.room_half


# ---------------------------------------------------------------------------
# §6.3 #16 — Ghost Vacuum admit predicate inversion (FLIP)
# ---------------------------------------------------------------------------


def test_phase_4c_c2_ghost_vacuum_per_aa_predicate_passes(
    ghost_vacuum_printing,
):
    """**§6.3 #16 (per-AA side).** Both Ghost Vacuum AAs PASS
    :func:`_aa_is_phase1_sub_shape_a` post-Phase-4C-C2 (Effect-class
    + sorcery_speed widens).
    """
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa0, aa1 = ghost_vacuum_printing.activated_abilities
    assert _aa_is_phase1_sub_shape_a(aa0) is True, (
        "AA[0] must pass per-AA gate (ExileTargetCardFromGraveyard "
        "Effect-class teeth lifted at C2)"
    )
    assert _aa_is_phase1_sub_shape_a(aa1) is True, (
        "AA[1] must pass per-AA gate (Effect-class + sorcery_speed "
        "teeth both lifted at C2)"
    )


def test_phase_4c_c2_ghost_vacuum_printing_predicate_passes(
    ghost_vacuum_printing,
):
    """**§6.3 #16 (printing side).** Live Ghost Vacuum printing PASSES
    the Artifact admit predicate + the top-level dispatcher post-Phase-
    4C-C2 widens.
    """
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    p = ghost_vacuum_printing
    assert _printing_is_bridge_simple_carrier_aa_artifact(p) is True
    assert _printing_is_bridge_simple_carrier_aa_any(p) is True
    # Land sibling stays decline (Ghost Vacuum is Artifact-typed, not Land).
    assert _printing_is_bridge_simple_carrier_aa_land(p) is False


def test_phase_4c_c2_ghost_vacuum_builder_emits_card_def(
    ghost_vacuum_printing,
):
    """**§6.3 #16 (builder side -- FULL FLIP).** The cross-engine
    Artifact builder :func:`_carrier_aa_artifact_card_def` emits a
    CardDef with the 2-AA bridge tuple. Unlike All-Fates Scroll's
    partial-FLIP (which decline at the builder gate on "any" coin
    teeth), Ghost Vacuum's two AAs both have closed-vocab Effects --
    so the FLIP closes end-to-end at C2.
    """
    from mtg_bot.parity.trajectory import _carrier_aa_artifact_card_def

    cd = _carrier_aa_artifact_card_def(ghost_vacuum_printing)
    assert cd is not None, (
        "Phase 4C C2 FULL FLIP: builder must emit CardDef for Ghost "
        "Vacuum (no honest-stop at builder gate, unlike Phase 4E "
        "partial-FLIP)"
    )
    assert cd.card_type == "Artifact"
    assert len(cd.activated_abilities) == 2


# ---------------------------------------------------------------------------
# Inverted Phase-4A walk -- Ghost Vacuum moves to ADMIT
# ---------------------------------------------------------------------------


def test_ghost_vacuum_admit_post_4c_c2_widens(ghost_vacuum_printing):
    """**Phase-4A walk inversion.** Ghost Vacuum admits at the
    production-deck admit gate post-Phase-4C-C2. Sibling of Phase 4E
    C2's :func:`test_phase_4_carrier_builder_gate_decline_post_c2`
    inversion for All-Fates Scroll's partial-FLIP.
    """
    from mtg_bot.parity.trajectory import (
        _carrier_aa_artifact_card_def,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    p = ghost_vacuum_printing
    assert _printing_is_bridge_simple_carrier_aa_artifact(p) is True
    assert _printing_is_bridge_simple_carrier_aa_any(p) is True
    cd = _carrier_aa_artifact_card_def(p)
    assert cd is not None


# ---------------------------------------------------------------------------
# Verify-first: walk the remaining Phase-4 carriers under widened gate
# (Mirrorpool, Keys to the House, All-Fates Scroll) to confirm no
# silent auto-grow.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def all_printings():
    from mtg_bot.cards.parser_source import OracleParserCardSource
    return OracleParserCardSource().get_printings()


def test_mirrorpool_still_declines_post_4c_c2(all_printings):
    """**No-silent-auto-grow pin (Mirrorpool -- 4B target).**
    Mirrorpool stays DECLINED post-Phase-4C-C2 because BOTH its AAs
    carry Effect classes not in the 11-entry admit set
    (CopyTargetInstantOrSorceryYouControl + Create...; Phase 4B
    ships the widen). The sorcery_speed widen does NOT silently flip
    Mirrorpool because the Effect-class teeth still bite.
    """
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    p = all_printings["Mirrorpool"]
    assert _printing_is_bridge_simple_carrier_aa_land(p) is False, (
        "Mirrorpool must STAY DECLINED post-Phase-4C-C2 -- Phase 4B "
        "ships the Effect-class widen"
    )
    assert _printing_is_bridge_simple_carrier_aa_any(p) is False


def test_keys_to_the_house_still_declines_post_4c_c2(all_printings):
    """**No-silent-auto-grow pin (Keys to the House -- 4D target).**
    Keys to the House carries AA[1] sorcery_speed=True (now admitted
    via the Phase-4C-C2 widen) but its Effect classes
    (SearchLibraryForCard's forward arm + LockOrUnlockDoor...) are
    not in the 11-entry admit set -- Phase 4D ships the Effect-class
    widen + the SearchLibraryForCard forward arm. Confirms that
    widening sorcery_speed alone does NOT silently flip Keys to the
    House (the Effect-class teeth still bite).
    """
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    p = all_printings["Keys to the House"]
    assert _printing_is_bridge_simple_carrier_aa_artifact(p) is False, (
        "Keys to the House must STAY DECLINED post-Phase-4C-C2 -- "
        "Phase 4D ships the Effect-class + SearchLibraryForCard "
        "forward arm widens"
    )
    assert _printing_is_bridge_simple_carrier_aa_any(p) is False


def test_all_fates_scroll_still_declines_at_builder_post_4c_c2(all_printings):
    """**No-silent-auto-grow pin (All-Fates Scroll -- Phase 4E
    partial-FLIP).** All-Fates Scroll's per-AA predicate already
    passes post-Phase-4E-C2; it STAYS DECLINED at the cross-engine
    builder gate via the "any" coin teeth in the AddManaToPool
    forward arm. The Phase-4C-C2 sorcery_speed widen does NOT flip
    its builder-gate decline (the "any" teeth bite at a different
    layer).
    """
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict
    from mtg_bot.parity.trajectory import _carrier_aa_artifact_card_def

    p = all_printings["All-Fates Scroll"]
    aa0 = p.activated_abilities[0]
    # Bridge floor still honest-declines on "any" teeth.
    assert _python_aa_to_safe_dict(aa0) is None
    # Builder still returns None.
    assert _carrier_aa_artifact_card_def(p) is None


def test_phase_1_3_admits_unchanged_post_4c_c2(all_printings):
    """**No-regression pin -- Phase-1-3 Carrier-AA Land admits stay
    admitted.** The 6 Phase-1-3 admits (Swarmyard / Deserted Temple /
    Petrified Field / Terrain Generator / Mystifying Maze / Scavenger
    Grounds) PLUS the Phase-3C Thespian's Stage admit STAY admitted
    post-Phase-4C-C2. No regression on the Land sibling.
    """
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_land,
    )

    expected_land_admits = (
        "Swarmyard",
        "Deserted Temple",
        "Petrified Field",
        "Terrain Generator",
        "Mystifying Maze",
        "Scavenger Grounds",
        "Thespian's Stage",
    )
    for name in expected_land_admits:
        p = all_printings[name]
        assert _printing_is_bridge_simple_carrier_aa_land(p) is True, (
            f"{name} must STILL ADMIT post-Phase-4C-C2 -- the "
            "sorcery_speed widen is strictly additive on the AA-rider "
            "axis; no Phase-1-3 admit carries sorcery_speed"
        )


# ---------------------------------------------------------------------------
# Cost-axis defense-in-depth -- sorcery_speed widen is per-AA-rider, not cost
# ---------------------------------------------------------------------------


def test_phase_4c_c2_widen_does_not_lift_other_riders():
    """**Bounded widen sanity.** The Phase-4C-C2 widen lifts ONLY the
    ``sorcery_speed=True`` decline arm; ``activate_only_once``,
    ``tier_threshold``, ``room_half``, and ``cost_reductions`` all
    stay decline-only.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    base_cost = ActivationCost(tap_self=True)
    base_effect = UntapTargetLand()

    # tier_threshold > 0 still declines.
    aa_tier = ActivatedAbility(
        cost=base_cost, effect=base_effect, tier_threshold=2,
    )
    assert _python_aa_to_safe_dict(aa_tier) is None
    # activate_only_once still declines.
    aa_once = ActivatedAbility(
        cost=base_cost, effect=base_effect, activate_only_once=True,
    )
    assert _python_aa_to_safe_dict(aa_once) is None


# ---------------------------------------------------------------------------
# Rust-side struct round-trip pin (the new sorcery_speed slot)
# ---------------------------------------------------------------------------


def test_phase_4c_c2_rust_activated_ability_accepts_sorcery_speed():
    """**Rust struct slot pin.** The Rust ``parse_activated_ability``
    parser accepts the optional ``sorcery_speed`` key on the registry
    dict; the round-trip through ``register_printing`` succeeds
    end-to-end on a synthetic printing carrying an
    ``ExileTargetCardFromGraveyard`` AA with sorcery_speed=True.

    The Rust side stores the flag on the new ``ActivatedAbility::
    sorcery_speed: bool`` slot (Phase 4C C2 -- cards.rs:11091).
    Data-carrying only at Rust today; the CR 605.3a activation-time
    legality gate defers to a follow-up cycle.
    """
    import importlib.util
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine  # noqa: F401

    # Build a minimal Artifact printing dict with one AA that carries
    # sorcery_speed=True + ExileTargetCardFromGraveyard.
    printing_dict = {
        "name": "Phase4cC2RustSorcerySpeedAA",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {"kind": "exile_target_card_from_graveyard"},
                "sorcery_speed": True,
            },
        ],
    }
    # Run through register_printing on a Registry -- should accept the
    # dict cleanly.
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(printing_dict)
    assert isinstance(pid, int) and pid >= 0


def test_phase_4c_c2_rust_activated_ability_rejects_non_bool_sorcery_speed():
    """**Rust struct slot pin -- type-check sanity.** The Rust
    ``parse_activated_ability`` raises a clean ``ValueError`` when
    ``sorcery_speed`` is not a Python bool (PyO3's
    ``v.extract::<bool>()`` rejects non-bool inputs via the
    map_err arm at ``rust/src/cards.rs:17753``). Mirrors the
    ``is_mana_ability`` + ``tier_threshold`` type-check shape.
    """
    import importlib.util
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine

    printing_dict = {
        "name": "Phase4cC2RustSorcerySpeedAABadType",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {"kind": "exile_target_card_from_graveyard"},
                "sorcery_speed": "yes",  # str, not bool
            },
        ],
    }
    reg = mtg_bot_engine.Registry()
    with pytest.raises(
        Exception, match="sorcery_speed must be a bool",
    ):
        reg.register_printing(printing_dict)


def test_phase_4c_c2_rust_activated_ability_defaults_sorcery_speed_false():
    """**Rust struct slot pin -- default value.** A registry dict
    that OMITS the ``sorcery_speed`` key registers cleanly and the
    AA's flag defaults to ``false`` (back-compat with every pre-Phase-
    4C-C2 caller).
    """
    import importlib.util
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine

    printing_dict = {
        "name": "Phase4cC2RustSorcerySpeedDefault",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {"kind": "exile_target_card_from_graveyard"},
                # sorcery_speed key omitted -> defaults to false
            },
        ],
    }
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(printing_dict)
    assert isinstance(pid, int) and pid >= 0


# ---------------------------------------------------------------------------
# Cross-engine bridge round-trip via the Rust register_printing path
# ---------------------------------------------------------------------------


def test_phase_4c_c2_ghost_vacuum_cross_engine_register_succeeds(
    ghost_vacuum_printing,
):
    """**Cross-engine register_printing pin.** A CardDef built from
    Ghost Vacuum via :func:`_carrier_aa_artifact_card_def` registers
    on the Rust side without error -- proves the full
    forward-emit ↔ Rust-parse round-trip works end-to-end on the
    live EoE printing.
    """
    import importlib.util
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine

    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict
    from mtg_bot.parity.trajectory import _carrier_aa_artifact_card_def

    cd = _carrier_aa_artifact_card_def(ghost_vacuum_printing)
    assert cd is not None
    printing_dict = _spec_card_to_printing_dict(cd)
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(printing_dict)
    assert isinstance(pid, int) and pid >= 0
    # The AA dict carries the sorcery_speed flag on AA[1] (Ghost
    # Vacuum's recall AA).
    aa_dicts = printing_dict.get("activated_abilities", [])
    assert len(aa_dicts) == 2
    assert aa_dicts[1].get("sorcery_speed") is True
    assert "sorcery_speed" not in aa_dicts[0]
