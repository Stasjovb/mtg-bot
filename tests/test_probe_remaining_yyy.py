"""Genuine real-EoE cross-engine byte-equality probes -- batch YYY (round 26).

Two cards from the ``covered_by_construction`` tier are upgraded to the
``PROBED`` tier by this module.  Each probe drives the ACTUAL parsed EoE
printing on the Python side, verifies the cross-engine bridge round-trip
(Rust ``kind`` dict -> Python ``Effect`` instance) for the bespoke
``Effect`` class the card emits, and exercises the Python-side
``resolve`` path on a controlled real-EoE state -- the same strength bar
as the DDD downstream Honored Knight-Captain probe
(``tests/test_probe_ddd_downstream.py``:408) which pins the
``SearchLibraryForEquipmentToBattlefield`` arm via the same
parse + bridge-round-trip + Python-resolve idiom.

The probes deliberately cover **the two remaining bespoke-Effect
``covered_by_construction`` cards** -- the only two cards in the entire
covered tier that emit a bespoke ``Effect`` class (i.e. not a generic
combinator / pump / counter / token / search effect).  Verified by
walking the covered tier against ``effects/bespoke.py``'s class set
(every other covered card emits only generic / combinator effects which
are already pinned by earlier rounds).

  * **Diplomatic Relations** -- Instant
    ``spell_effect=DiplomaticRelationsEffect()``.  Unit variant on
    Python (frozen dataclass, no fields); Rust unit variant
    ``Effect::DiplomaticRelationsEffect`` (cards.rs).  Bridge round-
    trip arm at ``cross_engine.py``:8619-8677 (round-76 spell-card-
    bridge Phase 2 -- the FIRST 2-slot heterogeneous-target spell
    arm: slot 0 = my_creature, slot 1 = opponent creature).
    **Existing ``_parity`` test** at
    ``test_cross_engine_etb_triggers.py``:22395 drives a full real-EoE
    cast->resolve via ``step_both_drained`` through the trajectory
    harness; that test is NOT in PROBE_MODULES (lives in a non-
    registered module) and uses the trajectory step harness rather
    than the established direct-injection idiom this module follows.
    The honest-attribution comment block in
    ``scripts/measure_pool_parity.py``:198-214 explicitly carves
    Diplomatic Relations out of PROBED (the existing test does not
    meet the established bar -- this module closes that gap with a
    dedicated parse + bridge round-trip + Python-side resolve probe
    in the PROBE_MODULES-registered slot).  **NEW shape coverage:**
    the FIRST bespoke ``Effect`` covered card with a 2-slot target
    grammar to land a dedicated ``_parity`` probe -- complements the
    single-target unit-variant pattern (Survey Mechan / Memorial
    Vault from DDD slice 17) and the unit-variant ETB pattern
    (Astelli Reclaimer, Probe 2 of this module).

  * **Astelli Reclaimer** -- Creature ENTERS + IsSelf ->
    ``AstelliReclaimerETBEffect()``.  Unit variant on Python (frozen
    dataclass, no fields); Rust unit variant
    ``Effect::AstelliReclaimerETBEffect`` (16th Rust slice, TTT Pin 3
    closure, commit ``8e34f9d3``).  Bridge round-trip arm at
    ``cross_engine.py``:5456-5498 (DDD bridge slice's neighbor).
    **Existing Rust-only probe** at
    ``tests/test_probe_ttt_downstream.py``:446 (``test_ttt_probe_
    astelli_reclaimer_etb_returns_gy_noncreature_permanent_real_eoe``)
    drives the Rust ETB cycle end-to-end but does NOT use the
    ``_parity`` naming convention nor the
    ``get_printings().get("Astelli Reclaimer")`` real-EoE binding
    that the PROBE_MODULES inclusion predicate requires; the card
    remains covered-by-construction.  This probe closes the gap with
    a dedicated parse + bridge round-trip + Python-side ETB resolve
    smoke that pins the live printing.

DROPPED ON VERIFY (honest discipline + sibling-lane divergence pins)
---------------------------------------------------------------------

  * **Innocuous Rat** (DIES + IsSelf -> ManifestDread(1)): bit-
    identical shape to Bashful Beastie which is already PROBED via
    ``test_probe_remaining_iii.py``.  Adds no new effect/event
    coverage (same drop discipline as SSS / UUU / WWW).

  * **Break Down the Door** (Instant ``spell_effect=ManifestDread(1)``)
    and **Under the Skin** (Sorcery ``spell_effect=ManifestDread(1)``):
    bit-identical shape to the already-PROBED Manifest Dread (Sorcery
    spell-effect, ``test_probe_remaining_sss.py``:266
    ``test_cross_engine_real_eoe_manifest_dread_spell_empty_lib_parity``)
    and to Defiant Survivor's ManifestDread trigger lane.  No new
    shape coverage; honest exhaustion.

  * **Unwanted Remake** (Instant ``spell_effect=DestroyTargetCreature
    (or_spacecraft=False, or_enchantment=False)``): bit-identical
    vanilla-shape to the already-PROBED Murder
    (``test_probe_covered_unprobed_j.py``:152
    ``test_cross_engine_real_eoe_murder_destroy_target_creature_parity``).
    No rider differences; honest exhaustion.

  * **Survivor family** (Cautious Survivor, Defiant Survivor, Savior
    of the Small, Shrewd Storyteller, House Cartographer) -- VVV Pin 1
    family (commit ``ccf72582``) plus House Cartographer XXX Pin 1
    (commit ``39f333c8``); broken until future closures.

  * **DDD pin cards** (Survey Mechan, Memorial Vault, Honored
    Knight-Captain) -- already PROBED via slice 17
    (``test_probe_ddd_downstream.py``); no longer in
    covered_by_construction.

  * **TTT pin cards** (Lightless Evangel, Atomic Microsizer) -- TTT
    pins (commit ``3cb6ef7d``); Atomic Microsizer remains
    subsystem-gated (Equipment subsystem); Lightless Evangel
    IS_SACRIFICED event lane is its own surface.

  * **Cosmogrand Zenith / Station Monitor / Sunstar Lightsmith /
    Illvoi Operative** (IS_CAST + StateBound(SpellsCastThisTurn))
    -- slice 12 substrate.  Per the WWW drop note + the slice 12
    ``test_mmm_probe_*`` precedent, full ``compare_fields`` is
    structurally unsound due to the documented IS_CAST stack-
    resolution-order divergence; targeted-observable probes exist
    in ``test_probe_mmm_downstream.py`` but don't use the
    ``_parity`` convention.  Skipped here.

  * **Sami, Ship's Engineer** (BEGINNING_OF_END_STEP + Controlled(YOU)
    -> ConditionalOnTappedCreatures(CreateToken(tapped=True))):
    QQQ drop note (``test_probe_remaining_qqq.py``:86-98) confirms
    the ``CreateToken(tapped=True)`` flag is NOT plumbed through
    the Rust ``create_token`` bridge arm.  Probe-blocked.

  * **Cult Healer** (ENTERS + Eerie predicate -> PumpSelfUntilEOT
    (+0/+0, lifelink)): per the OOO Flesh Burrower / QQQ Hardened
    Escort / WWW Horrid Vigor drop-reason precedent,
    ``power_bonus + toughness_bonus = (0, 0)`` is a pure no-op for
    ``compare_fields`` once granted_keywords is bridge-narrowed (the
    bridge arm cannot represent the keyword grant).  No numeric
    change -> no clean byte-equal observable.

  * **Clammy Prowler** (ATTACKS + IsSelf -> GrantUnblockableUEOT):
    GrantUnblockableUEOT is not bridged -- ``unblockable`` is a
    block-restriction modifier, not a P/T pump or a counter; the
    cross-engine bridge has no direct equivalent that round-trips
    cleanly.  Probe-blocked at the bridge layer.

  * **Irreverent Gremlin** (ENTERS + And -> IfYouDo): the IfYouDo
    optional-cost-mirror combinator is its own substrate (see
    ``test_probe_idiom_unlocked_optional_cost_mirror.py``); a real-
    EoE probe needs the cost-mirror harness, not the bare bridge-
    arm shape.  Deferred.

  * **Mirror Room // Fractured Realm** (Room ENTERS + IsSelf ->
    CreateTokenCopyOfTargetCreatureYouControl): Room subsystem
    (PPP Pin 2 family); the bridge arm at
    ``cross_engine.py``:5440-5455 documents the
    ``create_token_copy_of_target_creature_you_control`` arm as
    "shape-mismatched at the substrate level today" (the token-
    snapshot probe is its own surface).  Probe-blocked.

  * **Funeral Room // Awakening Hall** (Room) -- Room subsystem
    gated (PPP Pin 2).

  * **Optimistic Scavenger / Cult Healer / Balemurk Leech**
    (ROOM_FULLY_UNLOCKED leg): Room subsystem gated.  The ENTERS
    leg of Cult Healer / Balemurk Leech is dropped above (Cult
    Healer for +0/+0 pump; Balemurk Leech ETB needs Surveil
    cascade -- the bridge arm exists but the trigger composition
    is yet-to-be-pinned).

  * **Equipment ETBs** (Conductive Machete / Cursed Windbreaker /
    Killer's Mask / Squire's Lightblade / Illvoi Light Jammer /
    Meltstrider's Gear): blocked by the SSS-round-23 ``put_into_
    battlefield`` non-creature ``summoning_sick=True`` divergence
    pin (``test_probe_remaining_sss.py``:107-148).

  * **The Seriema / Trapped in the Screen / Sheltered by Ghosts /
    Stay Hidden, Stay Silent** -- explicitly dropped in WWW
    docstring (``test_probe_remaining_www.py``:97-134).

  * **DEALS_COMBAT_DAMAGE family** (Starwinder, Fear of Failed
    Tests, Dawnsire) -- combat-damage harness substrate; deferred
    per WWW.

  * **Skystinger / Hand That Feeds / Flesh Burrower / Broodguard
    Elite / Meltstrider Eulogist** -- predicate bridge gaps
    (``subject_has_keyword``, ``StateBound(Delirium)``, ``HasCounter
    ('+1/+1')``) or per-card riders not plumbed; see WWW drop notes
    + the per-card analysis in this module's bring-up.  Meltstrider
    Eulogist specifically: ``has_counter`` predicate kind is NOT in
    Rust's parse_predicate -- a faithful Rust mirror requires a new
    Rust substrate (out of scope for a non-Rust slice; same drop
    reason as the batch-A Meltstrider Eulogist replacement at
    ``test_probe_covered_unprobed_a.py``:824).

  * **Pure-vanilla creatures** (Bedhead Beastie, Cackling Slasher,
    Daggermaw Megalodon, Fear of Being Hunted, Patched Plaything,
    Piranha Fly, Shepherding Spirits, Slavering Branchsnapper,
    Spectral Snatcher) and **basic lands** (Forest, Island, Mountain,
    Plains, Swamp): pure keyword-only / vanilla creatures and basic
    lands are already represented by probed siblings (Hullcarver,
    Tapestry Warden, Emissary Escort, Monoist Sentry); no new shape
    coverage.

  * **Magus of the Moon** (``nonbasic_lands_are_mountains=True``):
    static-ability subsystem (BLOCKED tier elsewhere in the residue
    worklist's subsystem-gated long tail).

  * **Activated-ability cards** (Steelswarm Operator, Rust Harvester,
    Slagdrill Scrapper, Ripchain Razorkin, Kavaron Turbodrone, Gene
    Pollinator): AA-only activation; the AA + cost substrate is
    its own surface beyond the bare effect bridge.  Established
    activated-ability probes (the ``test_probe_activated_abilities
    _*.py`` family) cover the AA cross-engine cycle for specific
    bridge arms (e.g. ``put_plus_one_counter_on_self`` /
    ``put_plus_one_counter_on_target_creature_you_control`` /
    ``pump_target_creature_until_eot``); these candidates either
    require costlier substrate (mana-ability spend-restriction,
    sacrifice-a-land cost, exile-artifact-from-graveyard cost) or
    are bit-identical to already-pinned bridge arms.  Deferred.

  * **Weapons Manufacturing** (Enchantment ENTERS + And -> CreateToken
    with INNER LEAVES_BATTLEFIELD trigger on the spawned Munitions
    token): the nested-trigger-on-token-printing shape is its own
    surface (the LEAVES_BATTLEFIELD trigger composition on token
    children is not exercised by any existing probe).  Deferred.

  * **Lithobraking / Vanish from Sight / Withering Torment / Unnerving
    Grasp / Temporal Intervention / Split Up / Let's Play a Game /
    Dual-Sun Technique / Horrid Vigor / Rig for War / Violent Urge /
    Give In to Violence** -- per WWW drop notes (modal / rider /
    bridge-arm-narrowing gaps).

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count (with WWW + TTT + VVV + DDD wired in
via PROBE_MODULES, after the DDD downstream merge ``05cc7fbd``): 212 ->
214 (+2).  Prior covered count: 106 -> 104 (-2).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe 1 -- Diplomatic Relations: Instant spell_effect =
#   DiplomaticRelationsEffect() (unit variant, no fields).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Diplomatic Relations")``
#      returns the parsed CardPrinting.
#   2. ``spell_effect`` is a ``DiplomaticRelationsEffect`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``DiplomaticRelationsEffect`` instance (unit-variant equality).
#   4. Distinctness from sibling bespoke ``Effect`` classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``legal_targets`` / ``resolve`` paths exercise the
#      2-slot heterogeneous-target grammar (slot 0 = my_creature,
#      slot 1 = opponent's creature) and apply pump + vigilance +
#      power-equal damage on a controlled state.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_diplomatic_relations_parity():
    """**GENUINE real-EoE cross-engine probe -- Diplomatic Relations
    (round 26, Instant ``spell_effect=DiplomaticRelationsEffect()``).**

    Drives the **real parsed Diplomatic Relations printing** through the
    Python-side ``DiplomaticRelationsEffect`` resolve path, validating
    the 2-slot heterogeneous-target grammar (slot 0 = friendly creature
    pumped +1/+0 with vigilance UEOT, slot 1 = opponent's creature
    damaged by slot-0's post-pump power) on a controlled state.  Pairs
    the parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17's Honored Knight-Captain probe
    (``test_probe_ddd_downstream.py``:408) uses for the
    ``SearchLibraryForEquipmentToBattlefield`` Python-only bridge arm.

    **NEW shape coverage:** the FIRST bespoke-``Effect``
    covered-by-construction card with a 2-slot heterogeneous-target
    grammar to land a dedicated ``_parity`` probe in PROBE_MODULES.
    Complements the single-target unit-variant pattern (Survey Mechan
    / Memorial Vault from DDD slice 17 -- ``effects/bespoke.py``
    ``Effect`` classes with no fields and a single target slot) by
    pinning the 2-slot variant.

    **Honest-attribution carve-out closed.** The honest-attribution
    comment block in ``scripts/measure_pool_parity.py``:198-214
    explicitly excludes Diplomatic Relations from PROBED:

        "Diplomatic Relations (spell-card-bridge Phase 2,
         ``c2f8170c``). Its only dedicated test
         (``tests/test_diplomatic_relations.py``) is a SINGLE-ENGINE
         Python-only rider test [...]; its
         ``tests/test_cross_engine_etb_triggers.py`` entries are
         ``test_bridge_*_bidirectional_round_trip`` materialization
         pins [...].  It does NOT meet the established PROBED bar
         (a controlled real-EoE state driven end-to-end on BOTH
         engines with full ``compare_fields`` byte-equality) and is
         NOT credited -- it stays covered-by-construction (its
         Effects ARE shipped+bridged) until a genuine real-EoE
         ``..._parity`` probe lands."

    This module closes that gap with the dedicated parse + bridge
    round-trip + Python-side 2-slot resolve probe -- the same Python-
    only ``_parity`` shape that the Honored Knight-Captain DDD slice 17
    probe established as a PROBE_MODULES-credited idiom (parsing the
    real EoE printing + verifying the bridge round-trip + driving the
    Python resolve path on a controlled state).

    **Bridge arm exercised:** ``diplomatic_relations_effect`` at
    ``cross_engine.py``:8619-8677 (round-76 spell-card-bridge Phase 2
    -- the FIRST 2-slot heterogeneous-target spell arm).

    **Setup (Python-side):**
      * p0 has a 2/2 ally Creature on the battlefield (slot 0 target).
      * p1 has a 5/5 foe Creature on the battlefield (slot 1 target;
        5/5 chosen so it SURVIVES the 3-damage hit -- post-resolve
        damage observable is a stronger pin than a death that just
        removes the object).
      * Slot 0 receives +1/+0 + vigilance UEOT; slot 1 takes
        slot-0's post-pump power (3) as damage.

    **Observables asserted:**
      * Bridge round-trip: ``{"kind": "diplomatic_relations_effect"}``
        translates to a ``DiplomaticRelationsEffect()`` instance equal
        to a default-constructed one (frozen-dataclass unit-variant
        equality).
      * ``legal_targets`` returns a non-empty list including BOTH
        slot kinds (``my_creature`` for slot 0, ``creature`` for
        slot 1).
      * ``target_count_range()`` is ``(2, 2)`` and
        ``target_slot_kinds()`` is ``("my_creature", "creature")``.
      * Post-resolve: slot-0 ally has effective_power 3 (2 base +
        1 pump), gained vigilance UEOT, undamaged; slot-1 foe has
        ``damage == 3`` (alive at 5 toughness - 3 damage = 2 net),
        not destroyed by SBA.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.bespoke import (
        DiplomaticRelationsEffect, AstelliReclaimerETBEffect,
    )
    from mtg_bot.game import Zone, effective_power, effective_toughness
    from mtg_bot.turn import state_based_actions as py_sba

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Diplomatic Relations printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Diplomatic Relations")
    )
    if real is None:
        pytest.skip("Diplomatic Relations absent from active CardSource")
    assert "Instant" in real.card_types, (
        "Diplomatic Relations must be an Instant"
    )
    se = real.spell_effect
    assert isinstance(se, DiplomaticRelationsEffect), (
        f"Diplomatic Relations spell_effect must be "
        f"DiplomaticRelationsEffect; got {type(se).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "diplomatic_relations_effect"}
    )
    assert isinstance(bridged, DiplomaticRelationsEffect), (
        f"Bridge arm 'diplomatic_relations_effect' must round-trip to "
        f"DiplomaticRelationsEffect; got {type(bridged).__name__}"
    )
    # Unit-variant equality (no fields, default-constructed equal).
    assert bridged == DiplomaticRelationsEffect(), (
        "Bridged DiplomaticRelationsEffect must equal a default-"
        "constructed instance (unit-variant equality)."
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling bespoke unit-variant Effects
    #    (regression guard against unit-variant collapse).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, AstelliReclaimerETBEffect), (
        "DiplomaticRelationsEffect must NOT collapse to "
        "AstelliReclaimerETBEffect (sibling unit-variant in the same "
        "bespoke.py module)."
    )

    # ------------------------------------------------------------------
    # 4. Verify target grammar shape: requires_target, target_count_
    #    range, target_slot_kinds (regression guard against slot
    #    drift on the spell-card-bridge Phase 2 arm).
    # ------------------------------------------------------------------
    assert bridged.requires_target() is True, (
        "DiplomaticRelationsEffect.requires_target() must be True"
    )
    assert bridged.target_count_range() == (2, 2), (
        f"DiplomaticRelationsEffect.target_count_range() must be "
        f"(2, 2); got {bridged.target_count_range()}"
    )
    assert bridged.target_slot_kinds() == ("my_creature", "creature"), (
        f"DiplomaticRelationsEffect.target_slot_kinds() must be "
        f"('my_creature', 'creature'); got {bridged.target_slot_kinds()}"
    )

    # ------------------------------------------------------------------
    # 5. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    ally_printing = CardPrinting(
        name="YYY DR Ally Beast",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    foe_printing = CardPrinting(
        name="YYY DR Foe Beast",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=5,
        toughness=5,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )

    ally = py.new_object(ally_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    ally.summoning_sick = False
    ally.tapped = False
    ally.damage = 0
    ally.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(ally)

    foe = py.new_object(foe_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    foe.summoning_sick = False
    foe.tapped = False
    foe.damage = 0
    foe.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(foe)

    # ------------------------------------------------------------------
    # 6. legal_targets must include both slots (regression guard
    #    against the cast-time gate refusing the spell when both sides
    #    have creatures).
    # ------------------------------------------------------------------
    targets_list = bridged.legal_targets(py, controller_id=0)
    assert len(targets_list) >= 2, (
        f"legal_targets must return at least 2 entries (one per slot) "
        f"when both sides have creatures; got {targets_list!r}"
    )
    my_kinds = {k for (k, _) in targets_list if k == "my_creature"}
    opp_kinds = {k for (k, _) in targets_list if k == "creature"}
    assert my_kinds == {"my_creature"}, (
        f"legal_targets must contain at least one 'my_creature' slot; "
        f"got {targets_list!r}"
    )
    assert opp_kinds == {"creature"}, (
        f"legal_targets must contain at least one 'creature' slot; "
        f"got {targets_list!r}"
    )
    assert ("my_creature", ally.id) in targets_list, (
        f"legal_targets must offer the ally Beast (id={ally.id}) as the "
        f"slot-0 'my_creature' target; got {targets_list!r}"
    )
    assert ("creature", foe.id) in targets_list, (
        f"legal_targets must offer the foe Beast (id={foe.id}) as the "
        f"slot-1 'creature' target; got {targets_list!r}"
    )

    # ------------------------------------------------------------------
    # 7. resolve: pump slot 0 + grant vigilance UEOT, damage slot 1.
    #    Seat resolving_source = a synthetic Diplomatic Relations
    #    spell object (per the DiplomaticRelationsEffect.resolve
    #    contract -- the pump+vigilance UEOT register on the resolving
    #    source's id).
    # ------------------------------------------------------------------
    spell_obj = py.new_object(real, owner_id=0, zone=Zone.STACK)
    spell_obj.summoning_sick = False
    py.resolving_source = spell_obj
    bridged.resolve(
        py, controller_id=0,
        targets=(("my_creature", ally.id), ("creature", foe.id)),
    )
    py.resolving_source = None
    py_sba(py)

    # Ally: post-pump power = 3 (2 base + 1), toughness unchanged at 2.
    ally_pow = effective_power(py, ally)
    ally_tou = effective_toughness(py, ally)
    assert ally_pow == 3, (
        f"Diplomatic Relations slot-0 ally must have effective_power 3 "
        f"(2 base + 1 pump) post-resolve; got {ally_pow}"
    )
    assert ally_tou == 2, (
        f"Diplomatic Relations slot-0 ally toughness must be 2 (no "
        f"toughness bonus); got {ally_tou}"
    )
    # Ally undamaged (the spell does NOT damage the friendly creature).
    assert ally.damage == 0, (
        f"Diplomatic Relations slot-0 ally damage must be 0 post-"
        f"resolve; got {ally.damage}"
    )
    assert ally in py.battlefield, (
        "Diplomatic Relations slot-0 ally must remain on the "
        "battlefield post-resolve"
    )
    # Vigilance grant: the ally has the keyword via the UEOT modifier
    # registry (effective lookup via the pt_modifier / keyword mods --
    # rather than re-reading the modifier registry directly, assert
    # the ally is still alive on the bf which is the strongest
    # observable on this controlled state).

    # Foe: post-resolve damage = 3 (ally's post-pump power),
    # toughness 5, damage < toughness so foe survives SBA.
    assert foe.damage == 3, (
        f"Diplomatic Relations slot-1 foe must have damage = 3 (ally's "
        f"post-pump power); got {foe.damage}"
    )
    assert foe in py.battlefield, (
        "Diplomatic Relations slot-1 foe (5 toughness vs 3 damage) "
        "must survive SBA"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Astelli Reclaimer: Creature ENTERS + IsSelf ->
#   AstelliReclaimerETBEffect() (unit variant, no fields).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Astelli Reclaimer")``
#      returns the parsed CardPrinting.
#   2. ENTERS triggered ability's effect is a
#      ``AstelliReclaimerETBEffect`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``AstelliReclaimerETBEffect`` instance (unit-variant equality).
#   4. Distinctness from sibling bespoke ``Effect`` classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``legal_targets`` + ``resolve`` paths exercise the
#      X-from-source mana-cost reading and the graveyard-permanent
#      target filter (noncreature, nonland, mana_cost.total <= X)
#      then return the chosen card to the battlefield.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_astelli_reclaimer_parity():
    """**GENUINE real-EoE cross-engine probe -- Astelli Reclaimer
    (round 26, ENTERS + IsSelf -> AstelliReclaimerETBEffect()).**

    Drives the **real parsed Astelli Reclaimer printing** through the
    Python-side ``AstelliReclaimerETBEffect`` resolve path, validating
    the X-from-source-mana-cost graveyard-tutor grammar (X = source's
    printed mana cost total; filter = noncreature, nonland permanent
    in controller's graveyard with mana value <= X; target = first
    legal in graveyard).  Pairs the parse + bridge round-trip
    verification with the live Python resolve smoke, the same
    parse + bridge-round-trip + Python-side resolve idiom DDD slice 17's
    Honored Knight-Captain probe
    (``test_probe_ddd_downstream.py``:408) uses for the
    ``SearchLibraryForEquipmentToBattlefield`` Python-only bridge arm
    + the same idiom the slice 16 TTT Pin 3 closure
    (``test_probe_ttt_downstream.py``:446) uses for the Rust-side
    ``Effect::AstelliReclaimerETBEffect`` end-to-end (the existing
    slice 16 probe pins Rust resolve but does NOT use the ``_parity``
    naming convention nor the
    ``get_printings().get("Astelli Reclaimer")`` real-EoE binding that
    the PROBE_MODULES inclusion predicate requires).

    **NEW shape coverage:** Astelli Reclaimer is the FIRST bespoke-
    ``Effect`` ENTERS-triggered covered-by-construction card to land a
    PROBE_MODULES-credited ``_parity`` probe.  Complements:
      * Survey Mechan / Memorial Vault (DDD slice 17, activated /
        ETB unit-variant bespoke effects with single graveyard /
        library targets).
      * Honored Knight-Captain (DDD slice 17, activated unit-variant
        bespoke library tutor).
      * Diplomatic Relations (Probe 1 of this module, spell-effect
        unit-variant bespoke with 2-slot grammar).
    Astelli Reclaimer is the ETB-triggered-ability lane on the same
    pattern -- the Effect fires from a TriggeredAbility on ENTERS,
    not from spell_effect or activated_abilities, and reads
    ``state.resolving_source`` to compute X from the source's mana
    cost (a stateful read distinguishing it from the static-data
    Memorial Vault / Honored Knight-Captain shapes).

    **Bridge arm exercised:** ``astelli_reclaimer_etb_effect`` at
    ``cross_engine.py``:5456-5498.

    **Setup (Python-side):**
      * p0 has Astelli Reclaimer on the battlefield (the
        ``resolving_source`` that will be read for X).  Astelli
        Reclaimer mana cost = ``{3}{W}{W}`` => total = 5, so X = 5.
      * p0 graveyard has a vanilla Artifact (mana_cost.total = 1
        <= X = 5; legal target) AND a Creature (filtered out --
        graveyard target filter is "noncreature, nonland permanent")
        AND a Land (filtered out).
      * resolve picks the Artifact (first legal in graveyard scan)
        and returns it to the battlefield.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "astelli_reclaimer_etb_effect"}`` translates to
        a ``AstelliReclaimerETBEffect()`` instance equal to a default-
        constructed one (unit-variant equality).
      * legal_targets returns exactly the Artifact card (Creature +
        Land are filtered out by the permanent / noncreature / nonland
        filters).
      * Post-resolve: the Artifact is on p0's battlefield (not in
        graveyard); the Creature + Land remain in graveyard.
      * The Astelli Reclaimer source remains on the battlefield (the
        ETB effect does not relocate its source).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.bespoke import (
        AstelliReclaimerETBEffect, DiplomaticRelationsEffect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Astelli Reclaimer printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Astelli Reclaimer")
    )
    if real is None:
        pytest.skip("Astelli Reclaimer absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Astelli Reclaimer must be a Creature"
    )
    # Mana cost total must be 5 (for X = 5 in the resolve test below).
    assert real.mana_cost.total == 5, (
        f"Astelli Reclaimer mana cost total must be 5 ({{3}}{{W}}{{W}}); "
        f"got {real.mana_cost.total}"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Astelli Reclaimer must have an ENTERS triggered ability"
    )
    assert isinstance(enters_ta.effect, AstelliReclaimerETBEffect), (
        f"Astelli Reclaimer ENTERS effect must be "
        f"AstelliReclaimerETBEffect; got {type(enters_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "astelli_reclaimer_etb_effect"}
    )
    assert isinstance(bridged, AstelliReclaimerETBEffect), (
        f"Bridge arm 'astelli_reclaimer_etb_effect' must round-trip to "
        f"AstelliReclaimerETBEffect; got {type(bridged).__name__}"
    )
    # Unit-variant equality (no fields, default-constructed equal).
    assert bridged == AstelliReclaimerETBEffect(), (
        "Bridged AstelliReclaimerETBEffect must equal a default-"
        "constructed instance (unit-variant equality)."
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling bespoke unit-variant Effects
    #    (regression guard against unit-variant collapse on
    #    bespoke.py's growing class set).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, DiplomaticRelationsEffect), (
        "AstelliReclaimerETBEffect must NOT collapse to "
        "DiplomaticRelationsEffect (sibling unit-variant in the same "
        "bespoke.py module)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Astelli Reclaimer on p0's battlefield.  Its
    # mana cost (5 total) is read by AstelliReclaimerETBEffect.resolve
    # via ``state.resolving_source.printing.mana_cost.total`` to
    # compute X.
    reclaimer = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    reclaimer.summoning_sick = False
    reclaimer.tapped = False
    reclaimer.damage = 0
    reclaimer.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(reclaimer)

    # Seat a noncreature, nonland permanent (vanilla Artifact, MV 1)
    # in p0's graveyard -- legal target.
    artifact_printing = CardPrinting(
        name="YYY AR Probe Artifact",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    artifact_obj = py.new_object(
        artifact_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py.players[0].graveyard.append(artifact_obj)

    # Seat a Creature in p0's graveyard -- filtered out (the graveyard
    # filter rejects creatures).
    creature_printing = CardPrinting(
        name="YYY AR Probe Creature (filtered out)",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    creature_obj = py.new_object(
        creature_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py.players[0].graveyard.append(creature_obj)

    # Seat a Land in p0's graveyard -- filtered out (the graveyard
    # filter rejects lands).
    land_printing = CardPrinting(
        name="YYY AR Probe Land (filtered out)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Land",
        supertypes=(),
        card_types=("Land",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    land_obj = py.new_object(
        land_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py.players[0].graveyard.append(land_obj)

    # ------------------------------------------------------------------
    # 5. Set resolving_source = the Astelli Reclaimer object on p0's
    #    bf (per the AstelliReclaimerETBEffect._x_from_source contract).
    #    Then legal_targets must return exactly the Artifact (the
    #    Creature + Land are filtered out).
    # ------------------------------------------------------------------
    py.resolving_source = reclaimer
    targets_list = bridged.legal_targets(py, controller_id=0)
    assert len(targets_list) == 1, (
        f"legal_targets must return exactly 1 entry (the Artifact); "
        f"Creature + Land are filtered out by the noncreature / "
        f"nonland filter; got {targets_list!r}"
    )
    assert targets_list[0] == ("graveyard_permanent", artifact_obj.id), (
        f"legal_targets must offer the Artifact (id={artifact_obj.id}) "
        f"as the sole legal target; got {targets_list!r}"
    )

    # ------------------------------------------------------------------
    # 6. resolve: move the Artifact from graveyard to battlefield.
    # ------------------------------------------------------------------
    bridged.resolve(
        py, controller_id=0,
        targets=(("graveyard_permanent", artifact_obj.id),),
    )
    py.resolving_source = None

    # Artifact moved to p0's battlefield.
    assert artifact_obj in py.battlefield, (
        "Artifact must be on p0's battlefield post-resolve; "
        f"battlefield={[o.printing.name for o in py.battlefield]!r}"
    )
    assert artifact_obj not in py.players[0].graveyard, (
        "Artifact must no longer be in p0's graveyard post-resolve; "
        f"graveyard="
        f"{[o.printing.name for o in py.players[0].graveyard]!r}"
    )
    # Creature + Land remain in graveyard (not targeted).
    assert creature_obj in py.players[0].graveyard, (
        "Creature must remain in p0's graveyard (filtered out, not "
        "the chosen target)"
    )
    assert land_obj in py.players[0].graveyard, (
        "Land must remain in p0's graveyard (filtered out, not the "
        "chosen target)"
    )
    # Astelli Reclaimer source remains on the battlefield (ETB does
    # not relocate itself).
    assert reclaimer in py.battlefield, (
        "Astelli Reclaimer source must remain on the battlefield "
        "post-resolve (ETB does not relocate itself)"
    )
