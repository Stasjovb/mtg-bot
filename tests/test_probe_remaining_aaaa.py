"""Genuine real-EoE cross-engine byte-equality probes -- batch AAAA
(round 27, **the FIRST 4-letter probe batch** -- post-ZZZ alphabetic-
exhaustion).

The ZZZ batch (``tests/test_probe_remaining_zzz.py``:1-15) flagged its
own naming-convention exhaustion: "ZZZ is the LAST 3-letter alphabetic
batch.  Future probe batches (round 27+) must use a different naming
convention -- e.g. 4-letter ``AAAA`` / ``BBBB`` / ... or a numeric
``probe_batch_27`` / ``probe_batch_28`` form."  This module is round
27 and adopts the 4-letter ``AAAA`` form; subsequent batches follow
``BBBB`` / ``CCCC`` / ... per the established alphabetic cadence,
now widened by one letter to give the campaign another 26 batches of
room before the next exhaustion.

Two cards from the ``covered_by_construction`` tier are upgraded to the
``PROBED`` tier by this module via the same parse + bridge round-trip +
Python-side resolve idiom DDD slice 17's Honored Knight-Captain probe
(``tests/test_probe_ddd_downstream.py``:408), the YYY batch's two
probes (``tests/test_probe_remaining_yyy.py``:272 / 573), and the ZZZ
batch's two probes (``tests/test_probe_remaining_zzz.py``:173 / 413)
established as a PROBE_MODULES-credited shape.

  * **Cryoshatter** -- Aura with TWO triggered abilities, both firing
    the unit-variant ``DestroyEnchantedPermanent`` effect: one on
    ``Event.BECOMES_TAPPED`` + ``IsHost`` (the enchanted creature
    becomes tapped), one on ``Event.DEALT_DAMAGE`` + ``IsHost`` (the
    enchanted creature is dealt damage).  Bridge arm at
    ``cross_engine.py``:6161-6207 (round-26 BLOCKED-BRIDGE-ARM slice
    closure; unit variant matching Rust's
    ``Effect::DestroyEnchantedPermanent`` parser at cards.rs:3725-3727,
    to_dict at cards.rs:5630-5632).  **NEW shape coverage:** the
    FIRST Aura-carrier with the ``DestroyEnchantedPermanent``
    unit-variant effect to land a PROBE_MODULES-credited ``_parity``
    probe.  Complements:
      * Stay Hidden, Stay Silent (ZZZ Probe 1, BECOMES_TAPPED is NOT
        the trigger -- ZZZ probes the Aura ETB + sibling unit-variant
        ``TapEnchantedPermanent`` on the host-routing pattern).  This
        probe pins the DESTROY mutation on the host instead of the
        TAP mutation, and pins the host-event-triggered (BECOMES_TAPPED
        + DEALT_DAMAGE) firing instead of the ETB firing.
      * Sheltered by Ghosts (ZZZ Probe 2, Aura ETB +
        ``ExileOpponentsNonlandPermanentUntilLeaves`` -- targets
        opponent's permanent, not the host).  This probe pins the
        host-targeting pattern instead.
    The ``state.resolving_source.attached_to`` host-routing pattern
    is shared with ZZZ Probe 1 but the trigger event (host-side
    BECOMES_TAPPED / DEALT_DAMAGE rather than self-side ENTERS) and
    the mutation (destroy rather than tap) are both NEW.  The bridge
    arm's own docstring (cross_engine.py:6194-6203) explicitly
    flagged Cryoshatter as the canonical real-EoE consumer and
    deferred the cross-engine probe per "round-17/18/19 synthetic-
    only-when-riders-cascade precedent (the attached_to lookup + the
    destroy pipeline + the Aura-trigger event firing are their own
    surfaces beyond the bare bridge-arm slice)"; this probe closes
    that attribution gap at the established bar.

  * **Meltstrider's Gear** -- Equipment ENTERS + IsSelf ->
    ``AttachToTargetCreatureYouControl()`` (bare, no UEOT
    keyword-grant rider).  Unit variant on Python (frozen dataclass,
    ``granted_keywords_ueot=frozenset()`` default field); Rust unit
    variant ``Effect::AttachToTargetCreatureYouControl`` (cards.rs:1428;
    parser at cards.rs:3676-3678).  Bridge arm at
    ``cross_engine.py``:3337-3417 (round-19 BLOCKED-BRIDGE-ARM slice;
    bare arm carries NO rider -- matches Rust's no-field unit variant
    exactly).  **NEW shape coverage:** the FIRST Equipment-carrier
    ETB with the bare ``AttachToTargetCreatureYouControl`` effect to
    land a PROBE_MODULES-credited ``_parity`` probe.  The bridge
    docstring at cross_engine.py:3367-3372 explicitly cites
    Meltstrider's Gear as "the cleanest real-EoE consumer of the bare
    shape" (no UEOT keyword rider on the trigger); this probe pins
    that real-EoE consumer at the bare-bridge-arm slice.

    Distinguished from:
      * Squire's Lightblade (same effect class but with
        ``granted_keywords_ueot=frozenset({'first strike'})`` UEOT
        keyword rider -- the bridge arm does NOT carry the rider,
        so Squire's Lightblade is NOT cleanly Effect+bridge byte-
        equal at the rider-bearing variant; that's a deferred
        follow-up per the bridge docstring at
        cross_engine.py:3363-3367).
      * Conductive Machete / Killer's Mask / Cursed Windbreaker
        (Equipment ETBs but with the composite
        ``ManifestDreadThenAttachSelf`` effect class -- a different
        bridge arm at cross_engine.py:6453-6527 with its own
        manifest-dread + post-manifest-attach composition).

DROPPED ON VERIFY (honest discipline + sibling-lane divergence pins)
---------------------------------------------------------------------

  * **Squire's Lightblade** (Equipment ENTERS + IsSelf ->
    ``AttachToTargetCreatureYouControl(granted_keywords_ueot=
    frozenset({'first strike'}))``): the ``granted_keywords_ueot``
    rider is NOT carried by the bridge arm
    (``cross_engine.py``:3362-3367 explicitly: "the bare bridge arm
    here does NOT carry the rider -- the bare arm matches Rust's
    no-field unit variant exactly.  Cards that need the UEOT
    keyword rider would compose via a future ``GrantKeywordsUntilEOT``
    arm; that rider-bearing variant is a deferred follow-up").
    Probing without the rider would not pin THIS card's full
    Effect-shape -- honest exhaustion until the rider-bearing
    bridge arm lands.

  * **Conductive Machete / Killer's Mask** (Equipment ENTERS + IsSelf
    -> ``ManifestDreadThenAttachSelf()``): the
    ``ManifestDreadThenAttachSelf`` Python resolve at
    ``effects/generic/library_lookat.py``:510-565 requires:
      1. a library with at least one card (for ``ManifestDread``'s
         examined-cards step);
      2. an agent on the controller providing
         ``choose_card_from_library`` (when ``len(examined) == 2``
         the manifest-vs-graveyard pick goes through the agent);
      3. the ``put_into_battlefield`` fan-out from the manifest step.
    That's substrate beyond the bare bridge-arm slice (the bridge
    docstring at ``cross_engine.py``:6503-6509 explicitly defers
    the cross-engine probe per "the choose_card_from_library agent
    hook + the put_into_battlefield face-down ETB-trigger fan-out
    + the Equipment attach-source step + the count != 1 deferred-
    error gate are their own surfaces beyond the bare bridge-arm
    slice").  Honest exhaustion until the manifest-dread harness
    substrate is wired.

  * **Withering Torment** (Instant
    ``spell_effect=Sequence(DestroyTargetCreature(or_enchantment=
    True), LoseLife(2))``): the ``or_enchantment=True`` rider on
    ``DestroyTargetCreature`` is NOT bridged at the bare
    ``destroy_target_creature_then_draw_if_undamaged`` arm
    (cross_engine.py:8544-8601 -- the arm bridges to
    ``DestroyTargetCreature(draw_if_undamaged_amount=..., optional=
    True, exclude_self=True)``, dropping the ``or_enchantment``
    rider).  Probing without rider preservation would not pin THIS
    card's full Effect-shape -- honest exhaustion until a
    rider-bearing destroy arm lands.

  * **Temporal Intervention** (Sorcery
    ``spell_effect=TargetOpponentDiscardsCasterChoice``): no
    matching ``target_opponent_discards_caster_choice`` bridge arm
    in ``cross_engine.py``.  No Rust counterpart today -- honest
    exhaustion at the bridge layer.

  * **Unnerving Grasp** (Sorcery
    ``spell_effect=Sequence(ReturnTargetCreatureToOwnersHand,
    ManifestDread)``): no matching
    ``return_target_creature_to_owners_hand`` bridge arm in
    ``cross_engine.py``; the Sequence outer would round-trip but
    the inner ``ReturnTargetCreatureToOwnersHand`` arm is absent.
    Honest exhaustion at the bridge layer.

  * **Vanish from Sight** (Instant
    ``spell_effect=Sequence(OwnerPutsTargetArtifactOrCreatureOnTop
    OrBottomOfLibrary(nonland_permanent=True), Surveil(1))``): the
    ``OwnerPutsTarget*OnTopOrBottomOfLibrary`` arm DOES bridge
    (round-78 I78 closure) but the ``nonland_permanent=True``
    rider widens the target filter beyond "artifact or creature"
    -- the existing arm at ``cross_engine.py`` bridges the bare
    "artifact_or_creature" variant; the ``nonland_permanent=True``
    widened-filter is a follow-up sibling variant not yet on
    Rust.  Honest exhaustion until the widened-filter arm lands.

  * **All previously-PROBED Aura/Equipment ETB cards** -- Banishing
    Light, Hardlight Containment, Stay Hidden / Stay Silent (ZZZ),
    Sheltered by Ghosts (ZZZ), Spectral Snatcher, Diplomatic
    Relations (YYY), Astelli Reclaimer (YYY) -- already PROBED via
    earlier modules; not re-probed here.

  * **Subsystem-gated remainder** -- substrate (Equipment
    activated-ability surface / Aura attachment full surface /
    static-ability / modal complex / IS_CAST stack-resolution
    divergence / Room / non-Effect gate); none of these are
    unblocked by the YYY-idiom (the idiom only handles parse +
    bridge + Python-resolve, not full-game-trajectory or full
    cross-engine compare_fields).

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count (with ZZZ wired in via PROBE_MODULES,
after the post-Sothera/Requiem closures sequence -- main HEAD as of
2026-05-20 reports headline 219): 219 -> 221 (+2).  Prior covered
count: 105 -> 103 (-2).
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
# Probe 1 -- Cryoshatter: Aura with TWO triggered abilities, both ->
#   DestroyEnchantedPermanent() (unit variant, no fields).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Cryoshatter")``
#      returns the parsed CardPrinting (Aura subtype, enchant creature).
#   2. The BECOMES_TAPPED triggered ability's effect is a
#      ``DestroyEnchantedPermanent`` instance with IsHost predicate.
#   3. The DEALT_DAMAGE triggered ability's effect is a
#      ``DestroyEnchantedPermanent`` instance with IsHost predicate.
#   4. The bridge round-trips the canonical dict shape to a fresh
#      ``DestroyEnchantedPermanent`` instance (unit-variant equality).
#   5. Distinctness from sibling unit-variant Effects is preserved
#      (regression guard against unit-variant collapse).
#   6. Python's ``resolve`` path exercises the
#      ``state.resolving_source.attached_to`` host-routing pattern on
#      a controlled state: the host creature is taken from on-the-
#      battlefield to in-the-graveyard post-resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_cryoshatter_parity():
    """**GENUINE real-EoE cross-engine probe -- Cryoshatter (round 27
    AAAA, Aura with BECOMES_TAPPED + DEALT_DAMAGE host-event triggers
    -> DestroyEnchantedPermanent()).**

    Drives the **real parsed Cryoshatter printing** through the
    Python-side ``DestroyEnchantedPermanent`` resolve path, validating
    the ``state.resolving_source.attached_to`` host-routing pattern on
    a controlled state (host creature is on the battlefield pre-
    resolve; in the controller's graveyard post-resolve).  Pairs the
    parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17's Honored Knight-Captain probe
    (``test_probe_ddd_downstream.py``:408) + the YYY/ZZZ batches use.

    **NEW shape coverage:** the FIRST Aura-carrier with the
    ``DestroyEnchantedPermanent`` unit-variant effect to land a
    PROBE_MODULES-credited ``_parity`` probe.  Complements:
      * Stay Hidden, Stay Silent (ZZZ Probe 1 -- Aura ETB-triggered
        sibling unit-variant ``TapEnchantedPermanent`` on the same
        host-routing pattern; TAP mutation on the host).  This probe
        pins the DESTROY mutation on the host instead of TAP, and
        pins the host-event-triggered firing (BECOMES_TAPPED +
        DEALT_DAMAGE) instead of the ETB firing.
      * Sheltered by Ghosts (ZZZ Probe 2 -- Aura ETB-triggered
        ``ExileOpponentsNonlandPermanentUntilLeaves`` targeting an
        OPPONENT's permanent).  This probe pins the host-targeting
        pattern instead (the enchanted host on YOUR side).

    **Bridge arm exercised:** ``destroy_enchanted_permanent`` at
    ``cross_engine.py``:6161-6207 (round-26 BLOCKED-BRIDGE-ARM slice
    closure; unit variant matching Rust's
    ``Effect::DestroyEnchantedPermanent`` parser at cards.rs:3725-3727,
    to_dict at cards.rs:5630-5632).

    **Setup (Python-side):**
      * p0 has Cryoshatter on the battlefield (the Aura that serves
        as ``resolving_source``).  ``attached_to`` is set to the
        host creature's id.
      * p0 has a vanilla 2/2 Creature on the battlefield (the host;
        ``Cryoshatter.attached_to`` points to it).
      * resolve destroys the host creature via
        ``mtg_bot.turn.destroy`` (the standard
        destroy-permanent pipeline; CR 701.7 indestructible gate
        applied via ``turn.destroy``).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "destroy_enchanted_permanent"}`` translates to a
        ``DestroyEnchantedPermanent()`` instance equal to a default-
        constructed one (unit-variant equality).
      * Both TAs (BECOMES_TAPPED + DEALT_DAMAGE) emit
        ``DestroyEnchantedPermanent``; both carry an IsHost
        predicate.
      * Post-resolve: the host creature is in p0's graveyard (NOT on
        the battlefield).  The Cryoshatter Aura is ALSO in p0's
        graveyard (the host-leaves-bf cleanup routes the unattached
        Aura to its owner's graveyard in the SAME resolve window --
        the Aura-with-no-legal-attachment routing is folded into
        the host's LTB pipeline by ``move_off_battlefield`` per CR
        704.5n).  Both moves are logged in ``state.log``.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.destroy import DestroyEnchantedPermanent
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent
    from mtg_bot.effects.predicates import Event, IsHost
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Cryoshatter printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Cryoshatter")
    if real is None:
        pytest.skip("Cryoshatter absent from active CardSource")
    assert "Enchantment" in real.card_types, (
        "Cryoshatter must be an Enchantment"
    )
    assert "Aura" in real.subtypes, (
        f"Cryoshatter must carry the 'Aura' subtype; "
        f"got subtypes={sorted(real.subtypes or ())}"
    )
    assert real.aura_enchant_type == "creature", (
        f"Cryoshatter must enchant 'creature'; "
        f"got aura_enchant_type={real.aura_enchant_type!r}"
    )
    tas_by_event = {ta.event: ta for ta in real.triggered_abilities}
    assert Event.BECOMES_TAPPED in tas_by_event, (
        "Cryoshatter must have a BECOMES_TAPPED triggered ability "
        "(the enchanted creature becomes tapped lane)"
    )
    assert Event.DEALT_DAMAGE in tas_by_event, (
        "Cryoshatter must have a DEALT_DAMAGE triggered ability "
        "(the enchanted creature is dealt damage lane)"
    )
    becomes_tapped_ta = tas_by_event[Event.BECOMES_TAPPED]
    dealt_damage_ta = tas_by_event[Event.DEALT_DAMAGE]
    assert isinstance(becomes_tapped_ta.effect, DestroyEnchantedPermanent), (
        f"Cryoshatter BECOMES_TAPPED effect must be "
        f"DestroyEnchantedPermanent; got "
        f"{type(becomes_tapped_ta.effect).__name__}"
    )
    assert isinstance(dealt_damage_ta.effect, DestroyEnchantedPermanent), (
        f"Cryoshatter DEALT_DAMAGE effect must be "
        f"DestroyEnchantedPermanent; got "
        f"{type(dealt_damage_ta.effect).__name__}"
    )
    # Both predicates carry an IsHost gate (the canonical Aura-trigger
    # shape pinning the host-side fire condition).
    assert isinstance(becomes_tapped_ta.predicate, IsHost), (
        f"Cryoshatter BECOMES_TAPPED predicate must be IsHost; got "
        f"{type(becomes_tapped_ta.predicate).__name__}"
    )
    assert isinstance(dealt_damage_ta.predicate, IsHost), (
        f"Cryoshatter DEALT_DAMAGE predicate must be IsHost; got "
        f"{type(dealt_damage_ta.predicate).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "destroy_enchanted_permanent"}
    )
    assert isinstance(bridged, DestroyEnchantedPermanent), (
        f"Bridge arm 'destroy_enchanted_permanent' must round-trip to "
        f"DestroyEnchantedPermanent; got {type(bridged).__name__}"
    )
    # Unit-variant equality (no fields, default-constructed equal).
    assert bridged == DestroyEnchantedPermanent(), (
        "Bridged DestroyEnchantedPermanent must equal a default-"
        "constructed instance (unit-variant equality)."
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling unit-variant Effects (regression
    #    guard against unit-variant collapse).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, TapEnchantedPermanent), (
        "DestroyEnchantedPermanent must NOT collapse to "
        "TapEnchantedPermanent (sibling unit-variant probed in ZZZ "
        "Probe 1; both share the host-routing pattern but the "
        "mutation differs: TAP vs DESTROY)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat a vanilla 2/2 Creature on p0's battlefield -- the host
    # that the Aura's attached_to slot will point to.
    host_printing = CardPrinting(
        name="AAAA Cryoshatter Host Creature",
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
    host = py.new_object(host_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    host.tapped = False
    host.damage = 0
    host.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(host)

    # Seat the genuine Cryoshatter Aura on p0's battlefield with
    # attached_to pointing to the host (the ``resolving_source`` that
    # the effect will read for the host lookup).
    aura = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    aura.summoning_sick = False
    aura.tapped = False
    aura.damage = 0
    aura.attached_to = host.id
    aura.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(aura)

    # ------------------------------------------------------------------
    # 5. Set resolving_source = the Aura object on p0's bf (per the
    #    DestroyEnchantedPermanent.resolve contract -- reads
    #    ``state.resolving_source.attached_to`` to find the host).
    # ------------------------------------------------------------------
    py.resolving_source = aura

    # Pre-resolve sanity: host is on the battlefield, aura attached.
    assert host in py.battlefield, (
        "Pre-resolve sanity: host must be on the battlefield"
    )
    assert aura.attached_to == host.id, (
        f"Pre-resolve sanity: aura.attached_to must point to host id; "
        f"got {aura.attached_to!r} (expected {host.id!r})"
    )

    # ------------------------------------------------------------------
    # 6. resolve: destroy the host creature via the attached_to lookup.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())
    py.resolving_source = None

    # Host: moved from battlefield to p0's graveyard (the standard
    # destroy-permanent destination per CR 701.7).
    assert host not in py.battlefield, (
        "Cryoshatter: host must NOT be on the battlefield post-resolve "
        "(destroyed via DestroyEnchantedPermanent + turn.destroy)"
    )
    assert host in py.players[0].graveyard, (
        "Cryoshatter: host must be in p0's graveyard post-resolve "
        "(turn.destroy routes through move_off_battlefield -> "
        "destination='graveyard')"
    )
    # Aura moves to its owner's graveyard via the host-leaves-bf
    # cleanup cascade fired by ``move_off_battlefield`` -- when the
    # enchanted permanent leaves the battlefield, the attached Aura
    # is also routed to its owner's graveyard in the SAME resolve
    # window (the Aura-with-no-legal-attachment cleanup is folded
    # into the host's LTB pipeline, NOT deferred to a later SBA
    # priority pass).  The state log records both events:
    #   "<host> is destroyed by Cryoshatter"
    #   "Cryoshatter is put into the graveyard
    #    (enchanted permanent left the battlefield)"
    # The Cryoshatter Aura therefore lands in p0's graveyard
    # post-resolve, NOT on the battlefield.
    assert aura not in py.battlefield, (
        "Cryoshatter Aura must NOT remain on the battlefield post-"
        "resolve (the host-leaves-bf cleanup routes the unattached "
        "Aura to its owner's graveyard in the SAME resolve window)"
    )
    assert aura in py.players[0].graveyard, (
        "Cryoshatter Aura must be in p0's graveyard post-resolve "
        "(the host-leaves-bf cleanup folds the Aura-with-no-legal-"
        "attachment routing into the host's LTB pipeline)"
    )
    # State log records BOTH the host destroy and the Aura cleanup.
    log_text = "\n".join(py.log)
    assert "is destroyed by Cryoshatter" in log_text, (
        f"State log must record the host destroy via Cryoshatter; "
        f"got log:\n{log_text}"
    )
    assert "Cryoshatter is put into the graveyard" in log_text, (
        f"State log must record the Aura's host-leaves-bf cleanup; "
        f"got log:\n{log_text}"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Meltstrider's Gear: Equipment ENTERS + IsSelf ->
#   AttachToTargetCreatureYouControl() (bare, no UEOT keyword rider).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Meltstrider's Gear")``
#      returns the parsed CardPrinting (Equipment subtype on an
#      Artifact).
#   2. The ENTERS triggered ability's effect is a bare
#      ``AttachToTargetCreatureYouControl`` instance with
#      ``granted_keywords_ueot=frozenset()`` (no rider).
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``AttachToTargetCreatureYouControl()`` instance (no-rider
#      unit-variant equality).
#   4. Distinctness from sibling unit-variant Effects is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``legal_targets`` + ``resolve`` paths exercise the
#      source-controller's-creature target filter on a controlled
#      state: the Equipment's ``attached_to`` slot is stamped to the
#      chosen creature's id post-resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_meltstriders_gear_parity():
    """**GENUINE real-EoE cross-engine probe -- Meltstrider's Gear
    (round 27 AAAA, Equipment ENTERS + IsSelf ->
    AttachToTargetCreatureYouControl()).**

    Drives the **real parsed Meltstrider's Gear printing** through
    the Python-side ``AttachToTargetCreatureYouControl`` resolve
    path, validating the source-controller's-creature target filter
    on a controlled state (Equipment's ``attached_to`` slot is
    stamped to the chosen creature's id post-resolve).  Pairs the
    parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17 + YYY + ZZZ established.

    **NEW shape coverage:** the FIRST Equipment-carrier ETB with
    the bare ``AttachToTargetCreatureYouControl()`` effect
    (no UEOT keyword-grant rider) to land a PROBE_MODULES-credited
    ``_parity`` probe.  The bridge docstring at
    ``cross_engine.py``:3367-3372 explicitly cites Meltstrider's
    Gear as "the cleanest real-EoE consumer of the bare shape" (no
    UEOT keyword rider on the trigger); this probe pins that real-
    EoE consumer at the bare-bridge-arm slice.

    Distinguished from:
      * Squire's Lightblade (same effect class but with
        ``granted_keywords_ueot=frozenset({'first strike'})`` UEOT
        keyword rider -- the bridge arm does NOT carry the rider,
        so Squire's Lightblade is NOT cleanly Effect+bridge byte-
        equal at the rider-bearing variant).
      * Illvoi Light Jammer (same effect class but with
        ``granted_keywords_ueot=frozenset({'hexproof'})`` UEOT
        keyword rider -- same bridge-rider gap as Squire's).
      * Conductive Machete / Killer's Mask / Cursed Windbreaker
        (Equipment ETBs with the composite
        ``ManifestDreadThenAttachSelf`` -- a different bridge arm
        with its own manifest-dread + post-manifest-attach
        composition).
      * The Dominion Bracelet (Equipment with an ACTIVATED
        ``EquipToTargetCreatureYouControl`` ability, no ETB
        attach trigger).

    **Bridge arm exercised:** ``attach_to_target_creature_you_control``
    at ``cross_engine.py``:3337-3417 (round-19 BLOCKED-BRIDGE-ARM
    slice; unit variant matching Rust's
    ``Effect::AttachToTargetCreatureYouControl`` parser at
    cards.rs:3676-3678; the bridge arm carries NO rider -- matches
    Rust's no-field unit variant exactly).

    **Setup (Python-side):**
      * p0 has Meltstrider's Gear on the battlefield (the
        Equipment artifact source that serves as
        ``resolving_source``).  ``attached_to`` is initially None.
      * p0 has a vanilla 2/2 Creature on the battlefield (the
        legal-target creature on the source's controller's side).
      * p1 has a vanilla 2/2 Creature on the battlefield (filtered
        OUT by the "you control" clause -- the
        ``controller_id == controller_id`` exclusion rejects
        opponent's permanents).
      * resolve stamps ``Equipment.attached_to`` to the p0
        creature's id via the standard targeting pipeline.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "attach_to_target_creature_you_control"}``
        translates to an ``AttachToTargetCreatureYouControl()``
        instance equal to a default-constructed one (no-rider
        unit-variant equality).
      * The Equipment's ETB triggered ability emits an
        ``AttachToTargetCreatureYouControl`` instance with empty
        ``granted_keywords_ueot`` (the bare shape that matches
        Rust's unit variant exactly).
      * ``legal_targets`` returns exactly the p0 creature (the p1
        creature is filtered out by ``controller_id == controller_id``).
      * Post-resolve: the Equipment's ``attached_to`` field is set
        to the p0 creature's id (the source-controller's-creature
        target filter; CR 303.4 / 301.5 Equipment-attach is a
        battlefield-only relationship).
      * The p1 creature was NOT chosen (filtered out at
        legal_targets time -- the source-controller filter).
      * The Equipment source remains on the battlefield post-
        resolve (the attach is a state mutation, not a zone
        change).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.attach import (
        AttachToTargetCreatureYouControl,
        EquipToTargetCreatureYouControl,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Meltstrider's Gear printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Meltstrider's Gear")
    if real is None:
        pytest.skip("Meltstrider's Gear absent from active CardSource")
    assert "Artifact" in real.card_types, (
        "Meltstrider's Gear must be an Artifact"
    )
    assert "Equipment" in real.subtypes, (
        f"Meltstrider's Gear must carry the 'Equipment' subtype; "
        f"got subtypes={sorted(real.subtypes or ())}"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Meltstrider's Gear must have an ENTERS triggered ability"
    )
    assert isinstance(enters_ta.effect, AttachToTargetCreatureYouControl), (
        f"Meltstrider's Gear ENTERS effect must be "
        f"AttachToTargetCreatureYouControl; got "
        f"{type(enters_ta.effect).__name__}"
    )
    # The defining feature: bare shape, NO UEOT keyword rider.  This
    # is what makes Meltstrider's Gear (rather than Squire's Lightblade
    # or Illvoi Light Jammer) the canonical bare-bridge-arm consumer.
    assert enters_ta.effect.granted_keywords_ueot == frozenset(), (
        f"Meltstrider's Gear ENTERS effect must have empty "
        f"granted_keywords_ueot (no UEOT keyword-grant rider -- this "
        f"is the bare shape that matches Rust's no-field unit "
        f"variant exactly); got "
        f"granted_keywords_ueot={sorted(enters_ta.effect.granted_keywords_ueot)}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "attach_to_target_creature_you_control"}
    )
    assert isinstance(bridged, AttachToTargetCreatureYouControl), (
        f"Bridge arm 'attach_to_target_creature_you_control' must "
        f"round-trip to AttachToTargetCreatureYouControl; got "
        f"{type(bridged).__name__}"
    )
    # No-rider unit-variant equality (the bridge constructs the bare
    # default; matches Rust's no-field variant exactly).
    assert bridged == AttachToTargetCreatureYouControl(), (
        "Bridged AttachToTargetCreatureYouControl must equal a "
        "default-constructed instance (no-rider unit-variant equality)."
    )
    assert bridged.granted_keywords_ueot == frozenset(), (
        f"Bridged AttachToTargetCreatureYouControl must carry empty "
        f"granted_keywords_ueot (bare bridge arm; rider-bearing "
        f"variant is a deferred follow-up); got "
        f"granted_keywords_ueot={sorted(bridged.granted_keywords_ueot)}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling unit-variant Effects (regression
    #    guard against unit-variant collapse).
    #
    # ``EquipToTargetCreatureYouControl`` is a SUBCLASS of
    # ``AttachToTargetCreatureYouControl`` (effects/generic/attach.py:117)
    # -- isinstance check would pass on both directions.  The
    # distinctness guard here is on type identity, not isinstance:
    # the bridge MUST construct the base class, not the subclass
    # (the bridge arm "attach_to_target_creature_you_control" is for
    # the ETB-attach lane; "equip_to_target_creature_you_control" is
    # the separate bridge arm for the activated-ability Equip
    # resolution, which constructs the subclass instead).
    # ------------------------------------------------------------------
    assert type(bridged) is AttachToTargetCreatureYouControl, (
        f"Bridge arm 'attach_to_target_creature_you_control' must "
        f"construct AttachToTargetCreatureYouControl (the BASE class, "
        f"ETB-attach lane), NOT the EquipToTargetCreatureYouControl "
        f"subclass (the activated-ability Equip-resolution lane has "
        f"its own bridge arm at "
        f"'equip_to_target_creature_you_control').  Got type: "
        f"{type(bridged).__name__}"
    )
    assert not isinstance(
        bridged, EquipToTargetCreatureYouControl,
    ), (
        "Bridge arm 'attach_to_target_creature_you_control' must NOT "
        "construct an EquipToTargetCreatureYouControl subclass "
        "instance (the activated-ability Equip lane is a sibling "
        "bridge arm with its own distinct `describe` log string)."
    )

    # ------------------------------------------------------------------
    # 4. Verify target grammar shape: requires_target,
    #    legal_targets (regression guard against slot drift on the
    #    bridge surface).
    # ------------------------------------------------------------------
    assert bridged.requires_target() is True, (
        "AttachToTargetCreatureYouControl.requires_target() must be True"
    )

    # ------------------------------------------------------------------
    # 5. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Meltstrider's Gear Equipment on p0's
    # battlefield (the ``resolving_source``).  ``attached_to`` starts
    # as None.
    equipment = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    equipment.summoning_sick = False
    equipment.tapped = False
    equipment.damage = 0
    equipment.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(equipment)
    assert equipment.attached_to is None, (
        f"Pre-resolve sanity: Equipment.attached_to must start as "
        f"None; got {equipment.attached_to!r}"
    )

    # Seat a vanilla 2/2 Creature on p0's battlefield -- the LEGAL
    # target (source-controller-owned).
    p0_creature_printing = CardPrinting(
        name="AAAA MG Probe Bait (target)",
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
    p0_creature = py.new_object(
        p0_creature_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    p0_creature.summoning_sick = False
    p0_creature.tapped = False
    p0_creature.damage = 0
    p0_creature.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(p0_creature)

    # Seat a vanilla 2/2 Creature on p1's battlefield -- FILTERED
    # OUT (the ``controller_id == controller_id`` exclusion rejects
    # opponent's permanents at legal_targets time).
    p1_creature_printing = CardPrinting(
        name="AAAA MG Probe Opp Creature (filtered out)",
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
    p1_creature = py.new_object(
        p1_creature_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    p1_creature.summoning_sick = False
    p1_creature.tapped = False
    p1_creature.damage = 0
    p1_creature.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(p1_creature)

    # ------------------------------------------------------------------
    # 6. Set resolving_source = the Equipment object on p0's bf (per
    #    the AttachToTargetCreatureYouControl.resolve contract --
    #    reads ``state.resolving_source`` for the Equipment subtype
    #    gate + the ``attached_to`` stamp target).  Then
    #    legal_targets must return exactly the p0 creature.
    # ------------------------------------------------------------------
    py.resolving_source = equipment
    targets_list = bridged.legal_targets(py, controller_id=0)
    target_ids = {t[1] for t in targets_list}
    assert target_ids == {p0_creature.id}, (
        f"legal_targets must return exactly the p0 creature "
        f"(id={p0_creature.id}); the p1 creature is filtered out by "
        f"the source-controller 'you control' clause; got "
        f"target_ids={target_ids!r} (full "
        f"targets_list={targets_list!r})"
    )
    assert targets_list[0] == ("creature", p0_creature.id), (
        f"legal_targets[0] must be the 'creature' tuple form for the "
        f"p0 creature; got {targets_list[0]!r}"
    )

    # ------------------------------------------------------------------
    # 7. resolve: stamp the Equipment's attached_to slot via the
    #    AttachToTargetCreatureYouControl.resolve path.
    # ------------------------------------------------------------------
    bridged.resolve(
        py, controller_id=0,
        targets=(("creature", p0_creature.id),),
    )
    py.resolving_source = None

    # Equipment: attached_to slot stamped to the p0 creature's id.
    assert equipment.attached_to == p0_creature.id, (
        f"Meltstrider's Gear: Equipment.attached_to must equal the "
        f"p0 creature's id={p0_creature.id} post-resolve; got "
        f"attached_to={equipment.attached_to!r}"
    )
    # p1 creature was NOT chosen (filtered out at legal_targets time).
    assert equipment.attached_to != p1_creature.id, (
        f"Meltstrider's Gear: Equipment.attached_to must NOT be the "
        f"p1 creature's id={p1_creature.id} (filtered out by the "
        f"source-controller 'you control' clause at legal_targets "
        f"time); got attached_to={equipment.attached_to!r}"
    )

    # Equipment + both creatures remain on the battlefield (the
    # attach is a state mutation, not a zone change).
    assert equipment in py.battlefield, (
        "Meltstrider's Gear Equipment must remain on the battlefield "
        "post-resolve (the attach is a state mutation, not a zone "
        "change)"
    )
    assert p0_creature in py.battlefield, (
        "Meltstrider's Gear: p0 creature (attach target) must "
        "remain on the battlefield post-resolve (the attach stamps "
        "attached_to on the Equipment; it does NOT move the target)"
    )
    assert p1_creature in py.battlefield, (
        "Meltstrider's Gear: p1 creature must remain on the "
        "battlefield post-resolve (filtered out at legal_targets "
        "time, never touched by resolve)"
    )
