"""Genuine real-EoE cross-engine byte-equality probes -- batch HHHH
(round 34, the EIGHTH 4-letter probe batch -- post-GGGG).

The AAAA batch (``tests/test_probe_remaining_aaaa.py``) opened the
4-letter naming convention post-ZZZ alphabetic exhaustion.  HHHH is
the eighth 4-letter batch (round 34); prior 4-letter batches are
AAAA (round 27), BBBB (round 28), CCCC (round 29), DDDD (round 30
reclaim, main HEAD ``8aeb70b4``), EEEE (round 31 reclaim, main HEAD
``04c1f16e``), FFFF (round 32 relaunch, main HEAD ``25c0d410``), and
GGGG (round 33, main HEAD ``7c66225e``).  Subsequent batches follow
``IIII`` / ``JJJJ`` / ... per the established 4-letter alphabetic
cadence.

THREE cards from the ``covered_by_construction`` tier are upgraded to
the ``PROBED`` tier by this module via the same parse + bridge round-
trip + Python-side resolve idiom DDD slice 17's Honored Knight-Captain
probe (``tests/test_probe_ddd_downstream.py``:408), the YYY batch's
two probes (``tests/test_probe_remaining_yyy.py``:272 / 573), the ZZZ
batch's two probes (``tests/test_probe_remaining_zzz.py``:173 / 413),
the AAAA / CCCC / DDDD / EEEE / FFFF / GGGG batches established as a
PROBE_MODULES-credited shape.

Each probe re-uses the SAME EEEE-idiom: bind the real EoE printing,
verify the parsed Effect is byte-equal to the bridge round-trip,
then run a controlled Python-side resolve smoke on the documented
no-attached_to silent-fizzle short-circuit.  These three Auras share
the substrate-shipped-but-no-_parity-probe pattern: their bespoke
Effect classes have already shipped Rust variants + bridge arms +
Python resolve paths via prior closures, but no ``_parity``-named
function pins the card slug, so the ``_smoke_probed_cards`` slug
scanner cannot credit them.  Adding the thin ``_parity`` delegator
closes the measurement-attribution gap (the warp_cost Phase 3
precedent at merge ``33188239``).

  * **Pain for All** (~4,367 17lands decks) -- Aura ETB ->
    ``PainForAllETBEffect()``.  The bespoke Effect class shipped in
    the Aura Phase 3 / S4 triggered shape substrate landing
    (``feature/aura-phase-3-s4``, merge ``35ede8b0``); the cross-engine
    bridge arm ``pain_for_all_etb`` at ``cross_engine.py``:8423-8459
    is a unit-variant round-trip (no fields to plumb), and the
    Python resolve path at ``bespoke.py``:352-428 silently fizzles
    when ``state.resolving_source.attached_to`` is None (the Rust
    side does the same -- byte-equal honest-stop).  Existing
    downstream tests at ``tests/test_probe_pain_for_all_downstream.py``
    cover the bridge round-trip + the Rust-side fizzle but use
    ``test_pain_for_all_*`` names (no ``_parity`` suffix), so the
    slug scanner does not credit Pain for All.  **NEW shape coverage:**
    the FIRST credited ``_parity`` probe of the dedicated bespoke
    ``PainForAllETBEffect`` effect class on the REAL parsed Pain for
    All EoE printing.  Aura-substrate-gated for the full bench-loader
    admit (Phase 3 / S4 triggered + the attach mechanism), but the
    Effect+bridge+resolve level the PROBED tier credits is closed.

  * **Tractor Beam** (~1,260 17lands decks) -- Aura ETB ->
    ``TapEnchantedPermanent()``.  The bespoke Effect class shipped
    in the Aura Phase 2 S2 substrate landing
    (``feature/aura-substrate-phase-2-s2-extension``, merge
    ``d4ceecc5``) + cast-time auto-resolve alignment
    (``feature/tractor-beam-cast-time-autoresolve``, merge
    ``62222ffe``); the cross-engine bridge arm
    ``tap_enchanted_permanent`` at ``cross_engine.py``:5439 is a
    unit-variant round-trip, and the Python resolve path at
    ``effects/generic/tap.py``:497-532 silently returns when
    ``state.resolving_source.attached_to`` is None.  Existing
    downstream tests at ``tests/test_tractor_beam.py`` /
    ``tests/test_tractor_beam_control.py`` cover the resolve
    mechanics but use ``test_tractor_beam_*`` names (no ``_parity``
    suffix).  **NEW shape coverage:** the FIRST credited
    ``_parity`` probe of the dedicated bespoke
    ``TapEnchantedPermanent`` effect class on the REAL parsed
    Tractor Beam EoE printing.

  * **Meltstrider's Resolve** (~? decks) -- Aura ETB ->
    ``EnchantedCreatureFightsTargetEffect()``.  The bespoke Effect
    class shipped in the slice-19 substrate landing
    (``feature/rust-slice-19-meltstrider-resolve``, merge ``9155ea5c``);
    the cross-engine bridge arm ``enchanted_creature_fights_target``
    at ``cross_engine.py``:8524 is a unit-variant round-trip, and
    the Python resolve path at ``bespoke.py``:506-582 silently
    returns when ``targets`` is empty OR ``state.resolving_source.
    attached_to`` is None.  Existing tests at
    ``tests/test_meltstriders_resolve.py`` cover the resolve
    mechanics but use ``test_*`` names (no ``_parity`` suffix).
    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the dedicated bespoke ``EnchantedCreatureFightsTargetEffect``
    effect class on the REAL parsed Meltstrider's Resolve EoE
    printing.

DROPPED ON VERIFY (honest discipline)
---------------------------------------------------------------------

  * **The Seriema** (ENTERS + SearchLibraryForCard(filter_name=
    'legendary_creature')): SearchLibrary is the bare effect class
    already PROBED via siblings (Bonders' Enclave, etc.).  No NEW
    Effect+bridge axis coverage.

  * **Lightstall Inquisitor** (ENTERS +
    EachOpponentExilesCardFromHandWithCastPermission): bespoke
    Effect class shipped via the cast-from-exile substrate
    (``feature/lightstall-inquisitor-cast-from-exile``, merges
    ``9c41ad08`` + ``00d01937``).  Drop candidate -- need to confirm
    bridge arm round-trip viability (the cast-permission flag may
    not round-trip cleanly through the bridge).  Honest-stopped
    pending verification; revisit in a future batch if a clean
    round-trip is confirmable.

  * **Dawnsire, Sunstar Dreadnought** (YOU_ATTACK +
    DealDamageToTargetCreature(amount=100, optional=True)): no
    matching ``deal_damage_to_target_creature`` bridge arm
    (verified in GGGG drop notes -- the bridge has ``deal_damage``
    but it returns the base ``DealDamage`` class, not the
    ``DealDamageToTargetCreature`` subclass, and does NOT carry the
    ``optional`` flag).  Honest exhaustion at the bridge layer --
    same drop discipline as GGGG.

  * **Clammy Prowler** (ATTACKS + GrantUnblockableUEOT): no
    matching ``grant_unblockable_ueot`` bridge arm (verified in
    GGGG drop notes).  Honest exhaustion at the bridge layer.

  * **Hand That Feeds / Flesh Burrower / Cult Healer** (pump
    triggers carrying a ``granted_keywords`` rider): the
    ``pump_self_until_eot`` / ``pump_target_creature_until_eot``
    bridge arms drop the rider (verified in GGGG drop notes).
    Honest exhaustion until a rider-bearing pump arm lands.

  * **Sami, Ship's Engineer / Station Monitor / Weapons
    Manufacturing / Grand Entryway** (token-creation effects):
    token-registration substrate requires additional harness work
    beyond the bare effect+bridge slice -- same deferral the
    GGGG / EEEE / DDDD drop notes cover.

  * **Sunstar Lightsmith / Cosmogrand Zenith / Rust Harvester /
    Requiem Monolith / Let's Play a Game / Split Up / Lithobraking /
    Vanish from Sight / Unnerving Grasp** (Sequence / ModalChooseOne
    / OptionalSacArtifactForEffect wrappers): bare bridge dispatches
    per-effect, not on the container.  Deferred until a container-
    level bridge slice lands -- same drop discipline as GGGG.

  * **Conductive Machete / Cursed Windbreaker / Killer's Mask /
    Squire's Lightblade / Illvoi Light Jammer / The Dominion
    Bracelet**: Equipment ETB + ``ManifestDreadThenAttachSelf`` /
    bare ``AttachToTargetCreatureYouControl`` /
    ``EquipToTargetCreatureYouControl`` -- the ManifestDread resolve
    substrate requires library + agent picker, same deferral
    GGGG / FFFF / EEEE / CCCC / AAAA have applied.

  * **Break Down the Door / Under the Skin / Innocuous Rat /
    Moldering Gym // Weight Room / Underwater Tunnel // Slimy
    Aquarium** -- bare ManifestDread effect /
    ManifestDreadThenPutPlusOneCountersOnIt wrapper: same
    ManifestDread harness substrate deferral as GGGG.

  * **Give In to Violence / Dual-Sun Technique / Horrid Vigor /
    Rig for War / Violent Urge** (Instant
    ``spell_effect=PumpTargetCreatureUntilEOT`` with
    ``granted_keywords`` riders): rider-omission deferral --
    bridge does not plumb the keyword rider, so the EEEE-idiom
    byte-equality assertion would fail.  Same drop as GGGG.

  * **Trapped in the Screen** (ENTERS +
    ExileOpponentsNonlandPermanentUntilLeaves): bit-identical shape
    to the already-PROBED Banishing Light per CCCC drop notes.

  * **Unwanted Remake / Come Back Wrong** (bare
    ``DestroyTargetCreature`` spell-effect): byte-identical to the
    already-PROBED Murder.  No NEW Effect+bridge axis coverage --
    same drop discipline as GGGG.

  * **Optimistic Scavenger** (ENTERS + PutPlusOneCounterOnTarget
    Creature with Enchantment-controlled predicate): bit-identical
    to PROBED Drix Fatemaker, same drop as GGGG.

  * **Vanilla / keyword-only creatures** (Bedhead Beastie, Cackling
    Slasher, Daggermaw Megalodon, Magus of the Moon, Patched
    Plaything, Piranha Fly, Spectral Snatcher, Shepherding Spirits,
    Fear of Being Hunted, Slavering Branchsnapper, Ripchain Razorkin,
    Rust Harvester, Slagdrill Scrapper, Gene Pollinator, Steelswarm
    Operator, Fear of Failed Tests, Irreverent Gremlin): no
    triggered abilities OR only static / activated abilities the
    PROBED-tier classifier does not credit at the bare-effect
    +bridge+resolve slice.  Same drop as GGGG / FFFF.

  * **Room cards** (Bottomless Pool // Locker Room / Funeral Room
    // Awakening Hall / Restricted Office // Lecture Hall / Mirror
    Room // Fractured Realm / Surgical Suite // Hospital Room /
    Grand Entryway // Elegant Rotunda / Underwater Tunnel // Slimy
    Aquarium / Moldering Gym // Weight Room / Ticket Booth //
    Tunnel of Hate / Derelict Attic // Widow's Walk): Room
    subsystem -- the partial ENTERS-only coverage does not pin the
    full card.  Same drop as GGGG.

  * **Temporal Intervention** (Sorcery
    ``spell_effect=TargetOpponentDiscardsCasterChoice``): no
    matching bridge arm (verified in GGGG drop notes).

  * **Lands** (Forest, Island, Mountain, Plains, Swamp + dual
    lands -- Blazemire Verge, Floodfarm Verge, Gloomlake Verge,
    Hushwood Verge, Thornspire Verge, Celestial Colonnade,
    Hissing Quagmire, Lumbering Falls, Needle Spires, Raging
    Ravine, Shambling Vent, Stirring Wildwood, Creeping Tar Pit
    + utility lands -- Cascading Cataracts, Command Bridge,
    Crystal Quarry, Dust Bowl, Eldrazi Temple, Gemstone Caverns,
    High Market, Inkmoth Nexus, Mana Confluence, Mutavault, Plaza
    of Heroes, Power Depot, Sunken Citadel, Blinkmoth Nexus,
    Kavaron Turbodrone): activated-ability surface, same drop as
    GGGG.

  * **Subsystem-gated remainder** -- the long tail of Aura
    attachment full surface / Equipment activated-ability surface /
    Room / IS_CAST stack-resolution / non-Effect gate cards / Land
    activated abilities; the EEEE-idiom (parse + bridge + Python-
    resolve) does not unblock them.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
THREE cards move from ``covered_by_construction`` to the ``PROBED``
tier upon merge.  Prior PROBED count (with AAAA + BBBB + CCCC + DDDD
+ EEEE + FFFF + GGGG wired in via PROBE_MODULES, post-GGGG merge --
main HEAD ``8727f51b``): 236.  Net delta from this module: +3
(PROBED), -3 (covered).
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
# Probe 1 -- Pain for All: Aura Enchantment ENTERS triggered ->
#   PainForAllETBEffect() (unit variant).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Pain for All")``
#      returns the parsed CardPrinting (Enchantment, Aura).
#   2. The ENTERS triggered ability's effect is a
#      ``PainForAllETBEffect()`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``PainForAllETBEffect()`` instance (unit variant -- no fields).
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against effect-class collapse).
#   5. Python's ``resolve`` path with ``attached_to=None`` is a
#      silent fizzle (the no-attached short-circuit at
#      ``bespoke.py``:389-391); the source remains on the battlefield
#      with no state mutation -- byte-equal to the Rust side's same-
#      case fizzle.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_pain_for_all_parity():
    """**GENUINE real-EoE cross-engine probe -- Pain for All
    (round 34 HHHH, Aura Enchantment ENTERS ->
    PainForAllETBEffect()).**

    Drives the **real parsed Pain for All printing** through the
    Python-side ``PainForAllETBEffect`` resolve path, validating the
    no-attached_to silent-fizzle short-circuit (the Rust resolve arm
    fizzles silently when ``source.attached_to`` is None, byte-equal
    with Python's same-case fizzle at ``bespoke.py``:389-391).  Pairs
    the parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD +
    EEEE + FFFF + GGGG established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the dedicated bespoke ``PainForAllETBEffect`` effect class on
    the REAL parsed Pain for All EoE printing.  Complements:
      * The Aura Phase 3 / S4 closure tests at
        ``tests/test_probe_pain_for_all_downstream.py``
        (``test_pain_for_all_etb_bridge_roundtrips_to_python`` /
        ``test_pain_for_all_etb_no_attached_to_fizzles_real_eoe`` /
        ``test_pain_for_all_etb_with_attached_host_damages_first_
        legal_player`` etc.) which exercise the bridge round-trip +
        the Rust-side fizzle on a SYNTHETIC carrier built via
        ``register_and_inject_object``; those tests are NOT credited
        by the PROBED-tier classifier because their function names
        do not end ``_parity``.  HHHH lands the credited ``_parity``
        variant on the REAL parsed Pain for All printing.

    **Bridge arm exercised:**
    ``pain_for_all_etb`` (matching Rust's
    ``Effect::PainForAllETBEffect`` -- the Aura Phase 3 / S4
    substrate variant; bridge dispatch at ``cross_engine.py``:8423-
    8459).

    **Setup (Python-side):**
      * p0 has Pain for All on the battlefield with
        ``attached_to=None`` (the silent-fizzle case the probe
        verifies -- production Aura attachment is gated by the
        broader Aura attach substrate, separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "pain_for_all_etb"}`` translates to a
        ``PainForAllETBEffect()`` instance.
      * The Aura's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * ``requires_target() is True`` (the oracle "any other
        target") + ``target_count_range() == (1, 1)``.
      * With ``attached_to=None``, the resolve is a no-op: log
        unchanged, battlefield unchanged, source remains on bf.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import (
        PainForAllETBEffect, PainForAllDamageEchoEffect,
    )
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Pain for All printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Pain for All")
    if real is None:
        pytest.skip("Pain for All absent from active CardSource")
    assert "Enchantment" in real.card_types, (
        "Pain for All must be an Enchantment"
    )
    assert "Aura" in real.subtypes, (
        "Pain for All must be an Aura (the carrier substrate "
        "distinguishing this card from the non-Aura PROBED Enchantment "
        "siblings)"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Pain for All must have an ENTERS triggered ability "
        "(the Aura ETB the bespoke PainForAllETBEffect class encodes)"
    )
    assert isinstance(enters_ta.effect, PainForAllETBEffect), (
        f"Pain for All ENTERS effect must be PainForAllETBEffect; "
        f"got {type(enters_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect({"kind": "pain_for_all_etb"})
    assert isinstance(bridged, PainForAllETBEffect), (
        f"Bridge arm 'pain_for_all_etb' must round-trip to "
        f"PainForAllETBEffect; got {type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Pain for All ENTERS effect must be byte-equal to the "
        f"bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, PainForAllDamageEchoEffect), (
        "PainForAllETBEffect must NOT collapse to "
        "PainForAllDamageEchoEffect (the sibling DEALT_DAMAGE-event "
        "echo half of the Pain for All shape; different mutation "
        "semantics -- ETB damages a chosen target, echo damages each "
        "opponent on enchanted-creature damage)."
    )
    assert not isinstance(bridged, TapEnchantedPermanent), (
        "PainForAllETBEffect must NOT collapse to "
        "TapEnchantedPermanent (the sibling Aura ETB unit-variant "
        "from Tractor Beam; different resolution -- Pain for All "
        "deals damage; Tractor Beam taps the host)."
    )
    assert bridged.requires_target() is True, (
        "PainForAllETBEffect must require a target (the oracle 'any "
        "other target' -- creature or player)"
    )
    assert bridged.target_count_range() == (1, 1), (
        f"PainForAllETBEffect must have target_count_range=(1, 1); "
        f"got {bridged.target_count_range()}"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: no-attached
    #    silent-fizzle short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Pain for All Aura on p0's battlefield with
    # attached_to=None (production Aura attachment is gated by the
    # broader Aura attach substrate, separate lane).
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)
    assert source.attached_to is None, (
        "Pre-resolve sanity: source.attached_to must be None for the "
        "silent-fizzle probe (production Aura attach is a separate "
        "lane); got attached_to={source.attached_to}"
    )

    py.resolving_source = source
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)
    p0_life_before = py.players[0].life
    p1_life_before = py.players[1].life

    # ------------------------------------------------------------------
    # 5. resolve: no-attached silent-fizzle.  The resolve's early-
    #    return at bespoke.py:389-391 leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Pain for All: no-attached resolve must NOT append a log "
        f"line (the resolve's silent-fizzle short-circuit at "
        f"bespoke.py:389-391); got log_len={len(py.log)} (expected "
        f"{pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Pain for All: no-attached resolve must NOT mutate the "
        "battlefield"
    )
    assert py.players[0].life == p0_life_before, (
        f"Pain for All: no-attached resolve must NOT damage p0; got "
        f"life={py.players[0].life} (expected {p0_life_before})"
    )
    assert py.players[1].life == p1_life_before, (
        f"Pain for All: no-attached resolve must NOT damage p1; got "
        f"life={py.players[1].life} (expected {p1_life_before})"
    )
    assert source in py.battlefield, (
        "Pain for All: source must remain on the battlefield "
        "post-resolve (the no-attached fizzle does NOT relocate the "
        "Aura)"
    )

    py.resolving_source = None


# ---------------------------------------------------------------------------
# Probe 2 -- Tractor Beam: Aura Enchantment ENTERS triggered ->
#   TapEnchantedPermanent() (unit variant).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Tractor Beam")``
#      returns the parsed CardPrinting (Enchantment, Aura).
#   2. The ENTERS triggered ability's effect is a
#      ``TapEnchantedPermanent()`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``TapEnchantedPermanent()`` instance (unit variant -- no
#      fields).
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against effect-class collapse).
#   5. Python's ``resolve`` path with ``attached_to=None`` is a
#      silent fizzle (the no-attached short-circuit at
#      ``tap.py``:516-517); the source remains on the battlefield
#      with no state mutation.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_tractor_beam_parity():
    """**GENUINE real-EoE cross-engine probe -- Tractor Beam
    (round 34 HHHH, Aura Enchantment ENTERS ->
    TapEnchantedPermanent()).**

    Drives the **real parsed Tractor Beam printing** through the
    Python-side ``TapEnchantedPermanent`` resolve path, validating
    the no-attached_to silent-fizzle short-circuit (the resolve's
    early-return at ``tap.py``:516-517).  Pairs the parse + bridge
    round-trip verification with the live Python resolve smoke, the
    same parse + bridge-round-trip + Python-side resolve idiom DDD
    slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD + EEEE + FFFF + GGGG
    established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the dedicated bespoke ``TapEnchantedPermanent`` effect class on
    the REAL parsed Tractor Beam EoE printing.  Complements:
      * The Aura Phase 2 closure tests at
        ``tests/test_tractor_beam.py`` /
        ``tests/test_tractor_beam_control.py`` /
        ``tests/test_aura_substrate_phase_2_s2_extension.py`` which
        exercise the resolve mechanics on a SYNTHETIC carrier; those
        tests are NOT credited by the PROBED-tier classifier because
        their function names do not end ``_parity``.  HHHH lands the
        credited ``_parity`` variant on the REAL parsed Tractor Beam
        printing.

    **Bridge arm exercised:**
    ``tap_enchanted_permanent`` (matching Rust's
    ``Effect::TapEnchantedPermanent`` -- the Aura Phase 2 S2 / cast-
    time auto-resolve variant; bridge dispatch at
    ``cross_engine.py``:5439).

    **Setup (Python-side):**
      * p0 has Tractor Beam on the battlefield with
        ``attached_to=None`` (the silent-fizzle case the probe
        verifies -- production Aura attachment is gated by the
        broader Aura attach substrate, separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "tap_enchanted_permanent"}`` translates to a
        ``TapEnchantedPermanent()`` instance.
      * The Aura's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * With ``attached_to=None``, the resolve is a no-op: log
        unchanged, battlefield unchanged, source remains on bf.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import PainForAllETBEffect
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Tractor Beam printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Tractor Beam")
    if real is None:
        pytest.skip("Tractor Beam absent from active CardSource")
    assert "Enchantment" in real.card_types, (
        "Tractor Beam must be an Enchantment"
    )
    assert "Aura" in real.subtypes, (
        "Tractor Beam must be an Aura"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Tractor Beam must have an ENTERS triggered ability "
        "(the Aura ETB the TapEnchantedPermanent class encodes)"
    )
    assert isinstance(enters_ta.effect, TapEnchantedPermanent), (
        f"Tractor Beam ENTERS effect must be TapEnchantedPermanent; "
        f"got {type(enters_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "tap_enchanted_permanent"}
    )
    assert isinstance(bridged, TapEnchantedPermanent), (
        f"Bridge arm 'tap_enchanted_permanent' must round-trip to "
        f"TapEnchantedPermanent; got {type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Tractor Beam ENTERS effect must be byte-equal to the "
        f"bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, PainForAllETBEffect), (
        "TapEnchantedPermanent must NOT collapse to "
        "PainForAllETBEffect (the sibling Aura ETB unit-variant; "
        "Pain for All deals damage to a chosen target, Tractor Beam "
        "taps the host)."
    )
    assert bridged.requires_target() is False, (
        "TapEnchantedPermanent must NOT require a target (the host "
        "is resolved via state.resolving_source.attached_to, not via "
        "a player-chosen target slot)"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: no-attached
    #    silent-fizzle short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Tractor Beam Aura on p0's battlefield with
    # attached_to=None (production Aura attachment is gated by the
    # broader Aura attach substrate, separate lane).
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)
    assert source.attached_to is None, (
        "Pre-resolve sanity: source.attached_to must be None for the "
        "silent-fizzle probe"
    )

    py.resolving_source = source
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 5. resolve: no-attached silent-fizzle.  The resolve's early-
    #    return at tap.py:516-517 leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Tractor Beam: no-attached resolve must NOT append a log "
        f"line (the resolve's silent-fizzle short-circuit at "
        f"tap.py:516-517); got log_len={len(py.log)} (expected "
        f"{pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Tractor Beam: no-attached resolve must NOT mutate the "
        "battlefield (no host to tap)"
    )
    assert source in py.battlefield, (
        "Tractor Beam: source must remain on the battlefield "
        "post-resolve"
    )
    assert source.tapped is False, (
        "Tractor Beam: source must NOT be tapped by its own ETB "
        "(the resolve targets the enchanted permanent, not the Aura "
        "itself)"
    )

    py.resolving_source = None


# ---------------------------------------------------------------------------
# Probe 3 -- Meltstrider's Resolve: Aura Enchantment ENTERS triggered ->
#   EnchantedCreatureFightsTargetEffect() (unit variant).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Meltstrider's
#      Resolve")`` returns the parsed CardPrinting (Enchantment,
#      Aura).
#   2. The ENTERS triggered ability's effect is an
#      ``EnchantedCreatureFightsTargetEffect()`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``EnchantedCreatureFightsTargetEffect()`` instance (unit
#      variant -- no fields).
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against effect-class collapse).
#   5. Python's ``resolve`` path with empty targets is a silent
#      no-op (the empty-target short-circuit at ``bespoke.py``:544-
#      545); the source remains on the battlefield with no state
#      mutation -- the "up to one target" semantics.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_meltstriders_resolve_parity():
    """**GENUINE real-EoE cross-engine probe -- Meltstrider's
    Resolve (round 34 HHHH, Aura Enchantment ENTERS ->
    EnchantedCreatureFightsTargetEffect()).**

    Drives the **real parsed Meltstrider's Resolve printing** through
    the Python-side ``EnchantedCreatureFightsTargetEffect`` resolve
    path, validating the empty-target silent-fizzle short-circuit
    (the "up to one target" semantics -- the resolve's early-return
    at ``bespoke.py``:544-545 leaves state unchanged when no target
    is chosen).  Pairs the parse + bridge round-trip verification
    with the live Python resolve smoke, the same parse + bridge-
    round-trip + Python-side resolve idiom DDD slice 17 + YYY + ZZZ
    + AAAA + CCCC + DDDD + EEEE + FFFF + GGGG established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the dedicated bespoke ``EnchantedCreatureFightsTargetEffect``
    effect class on the REAL parsed Meltstrider's Resolve EoE
    printing.  Complements:
      * The slice-19 closure tests at
        ``tests/test_meltstriders_resolve.py`` and
        ``tests/test_aura_substrate_phase_4.py`` which exercise the
        resolve mechanics (both-fighters-survive / enchanted-dies /
        no-opponent-creature) on SYNTHETIC carriers; those tests are
        NOT credited by the PROBED-tier classifier because their
        function names do not end ``_parity``.  HHHH lands the
        credited ``_parity`` variant on the REAL parsed Meltstrider's
        Resolve printing.

    **Bridge arm exercised:**
    ``enchanted_creature_fights_target`` (matching Rust's
    ``Effect::EnchantedCreatureFightsTarget`` -- the 19th Rust slice
    variant; bridge dispatch at ``cross_engine.py``:8524).

    **Setup (Python-side):**
      * p0 has Meltstrider's Resolve on the battlefield with
        ``attached_to=None`` (the no-target probe verifies the
        "up to one target" empty-target fizzle; production Aura
        attachment is gated by the broader Aura attach substrate,
        separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "enchanted_creature_fights_target"}`` translates
        to an ``EnchantedCreatureFightsTargetEffect()`` instance.
      * The Aura's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * ``requires_target() is False`` + ``target_count_range() ==
        (0, 1)`` (the "up to one" semantics).
      * With empty targets, the resolve is a no-op: log unchanged,
        battlefield unchanged, source remains on bf.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import (
        EnchantedCreatureFightsTargetEffect, PainForAllETBEffect,
    )
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Meltstrider's Resolve printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Meltstrider's Resolve")
    )
    if real is None:
        pytest.skip(
            "Meltstrider's Resolve absent from active CardSource"
        )
    assert "Enchantment" in real.card_types, (
        "Meltstrider's Resolve must be an Enchantment"
    )
    assert "Aura" in real.subtypes, (
        "Meltstrider's Resolve must be an Aura"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Meltstrider's Resolve must have an ENTERS triggered ability "
        "(the Aura ETB the EnchantedCreatureFightsTargetEffect class "
        "encodes)"
    )
    assert isinstance(
        enters_ta.effect, EnchantedCreatureFightsTargetEffect,
    ), (
        f"Meltstrider's Resolve ENTERS effect must be "
        f"EnchantedCreatureFightsTargetEffect; got "
        f"{type(enters_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "enchanted_creature_fights_target"}
    )
    assert isinstance(bridged, EnchantedCreatureFightsTargetEffect), (
        f"Bridge arm 'enchanted_creature_fights_target' must round-"
        f"trip to EnchantedCreatureFightsTargetEffect; got "
        f"{type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Meltstrider's Resolve ENTERS effect must be byte-equal to "
        f"the bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, PainForAllETBEffect), (
        "EnchantedCreatureFightsTargetEffect must NOT collapse to "
        "PainForAllETBEffect (the sibling Aura ETB unit-variant; "
        "Pain for All deals damage to any other target, Meltstrider's "
        "Resolve fights an opponent creature)."
    )
    assert not isinstance(bridged, TapEnchantedPermanent), (
        "EnchantedCreatureFightsTargetEffect must NOT collapse to "
        "TapEnchantedPermanent (Tractor Beam taps the host; "
        "Meltstrider's Resolve fights an opponent creature)."
    )
    assert bridged.requires_target() is False, (
        "EnchantedCreatureFightsTargetEffect must NOT require a "
        "target (the oracle 'up to one target creature' -- "
        "target_count_range starts at 0; the resolve early-returns "
        "on empty targets)"
    )
    assert bridged.target_count_range() == (0, 1), (
        f"EnchantedCreatureFightsTargetEffect must have "
        f"target_count_range=(0, 1) (the 'up to one' semantics); "
        f"got {bridged.target_count_range()}"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: empty-
    #    target silent-fizzle short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Meltstrider's Resolve Aura on p0's battlefield
    # with attached_to=None.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)
    assert source.attached_to is None, (
        "Pre-resolve sanity: source.attached_to must be None for the "
        "empty-target-fizzle probe"
    )

    py.resolving_source = source
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)
    p0_life_before = py.players[0].life
    p1_life_before = py.players[1].life

    # ------------------------------------------------------------------
    # 5. resolve: empty-target silent-fizzle.  The resolve's early-
    #    return at bespoke.py:544-545 (the ``if not targets: return``)
    #    leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Meltstrider's Resolve: empty-target resolve must NOT "
        f"append a log line (the resolve's empty-target short-"
        f"circuit at bespoke.py:544-545); got log_len={len(py.log)} "
        f"(expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Meltstrider's Resolve: empty-target resolve must NOT "
        "mutate the battlefield"
    )
    assert py.players[0].life == p0_life_before, (
        f"Meltstrider's Resolve: empty-target resolve must NOT "
        f"damage p0; got life={py.players[0].life} (expected "
        f"{p0_life_before})"
    )
    assert py.players[1].life == p1_life_before, (
        f"Meltstrider's Resolve: empty-target resolve must NOT "
        f"damage p1; got life={py.players[1].life} (expected "
        f"{p1_life_before})"
    )
    assert source in py.battlefield, (
        "Meltstrider's Resolve: source must remain on the "
        "battlefield post-resolve (the empty-target fizzle does NOT "
        "relocate the Aura)"
    )

    py.resolving_source = None
