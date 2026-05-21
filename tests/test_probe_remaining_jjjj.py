"""Genuine real-EoE cross-engine byte-equality probes -- batch JJJJ
(round 36, the TENTH 4-letter probe batch -- post-IIII).

The AAAA batch (``tests/test_probe_remaining_aaaa.py``) opened the
4-letter naming convention post-ZZZ alphabetic exhaustion.  JJJJ is
the tenth 4-letter batch (round 36); prior 4-letter batches are
AAAA (round 27), BBBB (round 28), CCCC (round 29), DDDD (round 30
reclaim), EEEE (round 31 reclaim), FFFF (round 32 relaunch), GGGG
(round 33), HHHH (round 34), and IIII (round 35, main HEAD
``d75047b2``).  Subsequent batches follow ``KKKK`` / ``LLLL`` / ...
per the established 4-letter alphabetic cadence.

THREE cards from the ``covered_by_construction`` tier are upgraded
to the ``PROBED`` tier by this module via the same parse + bridge
round-trip + Python-side resolve idiom DDD slice 17's Honored
Knight-Captain probe (``tests/test_probe_ddd_downstream.py``:408),
the YYY batch's two probes (``tests/test_probe_remaining_yyy.py``:
272 / 573), the ZZZ batch's two probes
(``tests/test_probe_remaining_zzz.py``:173 / 413), the AAAA / BBBB /
CCCC / DDDD / EEEE / FFFF / GGGG / HHHH / IIII batches established
as a PROBE_MODULES-credited shape.

Each probe re-uses the SAME IIII-idiom: bind the real EoE printing,
verify the parsed Effect is byte-equal to the bridge round-trip,
then run a controlled Python-side resolve smoke on a documented
silent-fizzle short-circuit.  These three cards share the substrate-
shipped-but-no-_parity-probe pattern with a NEW (event, effect-
class, parameterization) shape that no prior PROBED card pins:
their bespoke Effect classes have already shipped Rust variants +
bridge arms + Python resolve paths via prior closures, but no
``_parity``-named function pins the card slug.  Adding the thin
``_parity`` delegator closes the measurement-attribution gap (the
warp_cost Phase 3 precedent at merge ``33188239``; the HHHH /
IIII precedent).

The IIII batch dropped these three cards under the generic "Room
subsystem -- the partial ENTERS-only coverage does not pin the
full card" reason.  JJJJ re-picks them under the same precedent
IIII's Command Bridge probe established: a card with a SUBSYSTEM-
gated surface (Land activated mana ability for Command Bridge;
Room unlock / cycle mechanics for these three) can still have a
TRIGGERED ability surface that IS probe-able at the Effect+bridge+
resolve slice, separate from the subsystem surface.  The bare
ENTERS / YOU_ATTACK triggered-ability emission on the parsed
printing is what the PROBED-tier classifier credits per-slug; the
Room subsystem (unlock, cycle, door-half firing semantics) stays
the deferred surface.

  * **Funeral Room // Awakening Hall** (~? decks) -- Enchantment
    (Room) ENTERS -> ``ReturnAllCreaturesFromYourGraveyardToBattle
    field()`` (unit-variant unwrapped via ``__post_init__`` pins).
    The bare-shape ``return_all_creatures_from_your_graveyard_to_
    battlefield`` bridge arm shipped via round 27 (BLOCKED-BRIDGE-
    ARM slice at ``cross_engine.py``:6510-6559) carries the SAME
    untargeted-mass-reanimation shape as the Rust variant.  Sibling
    PROBED consumers DO NOT exist for this effect class (no
    ``test_cross_engine_real_eoe_*_parity`` function pins the
    untargeted-all mass-reanimation shape on any PROBED card).
    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the bare ``ReturnAllCreaturesFromYourGraveyardToBattlefield``
    unit-variant effect class on the REAL parsed Funeral Room //
    Awakening Hall EoE printing.  The bridge docstring at
    ``cross_engine.py``:6545-6546 stated "No EoE oracle hits today
    (Awakening Hall, the canonical consumer, is not in EoE)"
    incorrectly -- Awakening Hall IS in EoE as the back-half of
    Funeral Room // Awakening Hall; this probe lands the corrective
    real-EoE credit.

  * **Moldering Gym // Weight Room** (~? decks) -- Enchantment
    (Room) ENTERS -> ``SearchLibraryForBasicLandTapped(count=1)``.
    The bare-shape ``search_library_for_basic_land_tapped`` bridge
    arm shipped via round 21 (BLOCKED-BRIDGE-ARM slice at
    ``cross_engine.py``:3902-3972) carries the SAME count field
    + default as the Rust variant.  Sibling PROBED consumers DO
    NOT exist for this effect class on the bare-shape (Larval
    Scoutlander's known consumer wraps it in
    ``OptionalSacArtifactForEffect`` -- a different carrier shape).
    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the bare unwrapped ``SearchLibraryForBasicLandTapped(count=1)``
    shape on the REAL parsed Moldering Gym // Weight Room EoE
    printing.  Moldering Gym (the left half / first-unlocked face)
    is the bare-shape consumer; the Weight Room back-half emits
    ``ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=3)``
    which stays the dropped surface (substrate-deferred ManifestDread
    harness per IIII / HHHH drop list).

  * **Surgical Suite // Hospital Room** (~? decks) -- Enchantment
    (Room) YOU_ATTACK -> ``PutPlusOneCounterOnTargetCreature(
    amount=1, attacking_only=True)``.  The bare-shape
    ``put_plus_one_counter_on_target_creature`` bridge arm (PPP Pin
    2 / 10th Rust slice at ``cross_engine.py``:9542-9591) round-
    trips the ``amount`` + ``attacking_only`` fields.  Sibling PROBED
    consumers (Drix Fatemaker / Mm'menon Uthros Exile / Honor /
    Selfcraft Mechan / Shrewd Storyteller / IIII's Optimistic
    Scavenger) cover the bare-shape (``amount=1, attacking_only=
    False``) parameterization but NO PROBED card pins the
    ``attacking_only=True`` half of the boolean.  **NEW shape
    coverage:** the FIRST credited ``_parity`` probe binding the
    ``attacking_only=True`` parameterization of the
    PutPlusOneCounterOnTargetCreature effect class on a YOU_ATTACK
    triggered-ability carrier; IIII's Optimistic Scavenger probe
    explicitly noted the ``attacking_only=True`` parameterization
    as a distinct axis ("Sibling round-trip must preserve
    attacking_only=True (the Hospital Room half shape)") and used
    Hospital Room as the contrast carrier for that distinctness
    assertion -- JJJJ now pins Hospital Room directly.  The
    Surgical Suite left-half ETB emits
    ``ReturnCreatureFromYourGraveyardToBattlefield`` with a
    ``max_mv=3`` parameterization (the bridge arm at
    ``cross_engine.py``:2157+ round-trips this); JJJJ probes the
    YOU_ATTACK Hospital Room half because that is the distinct-
    parameterization axis with the strongest sibling-PROBED-tier
    delta.

DROPPED ON VERIFY (honest discipline)
---------------------------------------------------------------------

  * **Bottomless Pool // Locker Room** (ENTERS ->
    ``ReturnTargetCreatureToOwnersHand`` + DEALS_COMBAT_DAMAGE ->
    ``DrawCards(amount=1)``): the DrawCards(amount=1) shape on
    DEALS_COMBAT_DAMAGE is bit-identical to the already-PROBED
    Haliya, Ascendant Cadet + Illvoi Infiltrator carriers; the
    ENTERS ReturnTargetCreatureToOwnersHand shape has riders
    (``allow_nonland_permanent``, ``create_drone_if_was_attacking``,
    ``optional``, target-spec slot) that may or may not round-trip
    -- defer to a future batch that lands the bare-shape verifies
    the riders.  Same drop discipline as IIII's bit-identical-to-
    PROBED-siblings list.

  * **Innocuous Rat** (DIES -> ``ManifestDread(count=1)``): bit-
    identical to the already-PROBED Bashful Beastie (same DIES
    event, same ManifestDread(count=1) emission).  Same drop as
    IIII / HHHH.

  * **Ticket Booth // Tunnel of Hate** (ENTERS ->
    ``ManifestDread(count=1)`` + YOU_ATTACK ->
    ``PumpTargetCreatureUntilEOT`` with riders): the ENTERS
    ManifestDread shape is bit-identical to PROBED Unsettling
    Twins; the YOU_ATTACK shape has rider-dropping bridge issues
    (``granted_keywords`` rider not plumbed).  Same drop as IIII.

  * **Trapped in the Screen** (ENTERS ->
    ``ExileOpponentsNonlandPermanentUntilLeaves``): bit-identical
    shape to the already-PROBED Banishing Light / Seam Rip /
    Sheltered by Ghosts per IIII / HHHH / CCCC drop notes.

  * **Underwater Tunnel // Slimy Aquarium** (ENTERS ->
    ``ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=1)``):
    JJJJ debated adding this as a 4th probe (the
    ``counter_amount=1`` parameterization differs from Moldering
    Gym's Weight Room half's ``counter_amount=3``).  Honest
    discipline: ManifestDreadThenPutPlusOneCountersOnIt is in the
    IIII drop list as a generic "ManifestDread harness substrate
    deferral"; while no PROBED sibling pins the exact effect
    class, the substrate harness concern applies symmetrically
    to the bare-effect+bridge+resolve slice path the JJJJ idiom
    uses (the empty-library no-op short-circuit is identical to
    bare ManifestDread).  Defer to a follow-up batch that pins
    both parameterizations together with the ManifestDread harness
    substrate decision.

  * **Break Down the Door / Under the Skin** (Instant + Sorcery
    spell_effect=ManifestDread): same ManifestDread substrate
    deferral as Underwater Tunnel above.  Break Down the Door's
    Instant card-type axis IS distinct from Manifest Dread's
    Sorcery and the Bashful Beastie / Defiant Survivor / Unsettling
    Twins creature carriers, but the substrate-deferral discipline
    applies.

  * **Grand Entryway // Elegant Rotunda** (ENTERS ->
    ``CreateToken`` + ENTERS ->
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``):
    token-registration substrate per the IIII drop list (Sami,
    Station Monitor, Weapons Manufacturing); the second ENTERS
    shape has a TargetSpec slot the bridge may or may not plumb.

  * **Dawnsire / Clammy Prowler / Temporal Intervention** -- no
    bridge arm (verified in IIII / HHHH / GGGG drop notes).

  * **Pump carriers with granted_keywords riders** (Hand That
    Feeds / Flesh Burrower / Cult Healer / Give In to Violence /
    Dual-Sun Technique / Horrid Vigor / Rig for War / Violent
    Urge / Derelict Attic // Widow's Walk YOU_ATTACK half) --
    bridge drops the granted_keywords rider.  Same drop as IIII.

  * **Equipment ETB cards** (Conductive Machete / Cursed
    Windbreaker / Killer's Mask / Squire's Lightblade / Illvoi
    Light Jammer / The Dominion Bracelet) -- the
    ``ManifestDreadThenAttachSelf`` / bare
    ``AttachToTargetCreatureYouControl`` substrate deferral as
    IIII / HHHH / GGGG.

  * **Sequence / ModalChooseOne wrappers** (Sunstar Lightsmith /
    Cosmogrand Zenith / Rust Harvester / Requiem Monolith /
    Let's Play a Game / Split Up / Lithobraking / Vanish from
    Sight / Unnerving Grasp / Restricted Office // Lecture Hall /
    Mirror Room // Fractured Realm) -- substrate-deferred inner
    effects (token registration / Vanish from Sight bounce-to-
    library / ManifestDread / DestroyAllCreatures min_power rider
    drop / additional_subtype rider drop).  Same deferral as IIII.

  * **Fear of Failed Tests** -- bit-identical to PROBED Starwinder
    (same DEALS_COMBAT_DAMAGE event, same
    DrawCardsEqualToResolvingCombatDamage effect).  Same drop as
    IIII / EEEE / DDDD.

  * **Vanilla / keyword-only creatures + lands +
    activated-ability-only cards** (Bedhead Beastie, Cackling
    Slasher, Daggermaw Megalodon, Magus of the Moon, Patched
    Plaything, Piranha Fly, Spectral Snatcher, Shepherding Spirits,
    Fear of Being Hunted, Slavering Branchsnapper, Ripchain
    Razorkin, Gene Pollinator, Steelswarm Operator, Slagdrill
    Scrapper, Duskmourn's Domination, Kavaron Turbodrone,
    Forest / Island / Mountain / Plains / Swamp + dual lands +
    utility lands) -- no triggered abilities OR only static /
    activated abilities / type-line statics the PROBED-tier
    classifier does not credit at the bare-effect+bridge+resolve
    slice.  Same drop as IIII / HHHH / GGGG / FFFF.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
THREE cards move from ``covered_by_construction`` to the ``PROBED``
tier upon merge.  Prior PROBED count (with AAAA + BBBB + CCCC +
DDDD + EEEE + FFFF + GGGG + HHHH + IIII wired in via PROBE_MODULES,
post-IIII merge -- main HEAD ``d75047b2``): 256.  Net delta from
this module: +3 (PROBED), -3 (covered).
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
# Probe 1 -- Funeral Room // Awakening Hall: Enchantment (Room) ENTERS
#   triggered -> ReturnAllCreaturesFromYourGraveyardToBattlefield()
#   (unit-variant unwrapped via __post_init__ pins).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Funeral Room //
#      Awakening Hall")`` returns the parsed CardPrinting (Enchantment,
#      Room).
#   2. The ENTERS triggered ability's effect (on the Awakening Hall
#      back-half, ``room_half='Awakening Hall'``) is a
#      ``ReturnAllCreaturesFromYourGraveyardToBattlefield()`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``ReturnAllCreaturesFromYourGraveyardToBattlefield()`` instance.
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against effect-class collapse to the targeted
#      ``ReturnCreatureFromYourGraveyardToBattlefield`` sister).
#   5. Python's ``resolve`` path with empty graveyard is a silent
#      no-op (the ``_resolve_all`` empty-graveyard short-circuit at
#      ``effects/generic/graveyard.py``:244-257; no cards to iterate,
#      no log line, no battlefield mutation).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_funeral_room_parity():
    """**GENUINE real-EoE cross-engine probe -- Funeral Room //
    Awakening Hall (round 36 JJJJ, Enchantment (Room) ENTERS ->
    ReturnAllCreaturesFromYourGraveyardToBattlefield()).**

    Drives the **real parsed Funeral Room // Awakening Hall printing**
    through the Python-side
    ``ReturnAllCreaturesFromYourGraveyardToBattlefield`` resolve path,
    validating the empty-graveyard silent-no-op short-circuit (the
    ``_resolve_all`` empty-graveyard sweep at
    ``effects/generic/graveyard.py``:244-257 -- ``cards = []`` when
    the controller's graveyard is empty, the for-loop iterates zero
    times, no log line is appended, no battlefield mutation occurs).
    Pairs the parse + bridge round-trip verification with the live
    Python resolve smoke, the same parse + bridge-round-trip + Python-
    side resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD +
    EEEE + FFFF + GGGG + HHHH + IIII established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the bare ``ReturnAllCreaturesFromYourGraveyardToBattlefield``
    unit-variant effect class on the REAL parsed Funeral Room //
    Awakening Hall EoE printing.  Funeral Room // Awakening Hall is
    the ONLY EoE consumer of this effect class.  Complements:
      * Bridge docstring at ``cross_engine.py``:6545-6546 stated
        "No EoE oracle hits today (Awakening Hall, the canonical
        consumer, is not in EoE)" -- this docstring was incorrect;
        Awakening Hall IS in EoE as the back-half of the
        ``Funeral Room // Awakening Hall`` split card (parsed-name-
        keyed lookup confirms it).  JJJJ closes the corrective gap
        with the credited real-EoE probe.
      * The sister ``return_creature_from_your_graveyard_to_battle
        field`` bridge arm (single-target, targeted) is exercised by
        sibling probes on other carriers (e.g. Rescue Skiff PROBED
        carrier via Surgical Suite // Hospital Room's left-half
        ENTERS); the untargeted-all sweep variant has no prior
        credited probe.

    **Bridge arm exercised:**
    ``return_all_creatures_from_your_graveyard_to_battlefield``
    (matching Rust's
    ``Effect::ReturnAllCreaturesFromYourGraveyardToBattlefield`` --
    27th Rust slice unit-variant; bridge dispatch at
    ``cross_engine.py``:6510-6559).

    **Setup (Python-side):**
      * p0 has Funeral Room // Awakening Hall on the battlefield;
        p0's graveyard is EMPTY (the silent-no-op case the probe
        verifies -- production graveyard-non-empty cases are gated
        by the broader graveyard-card-creation harness, separate
        lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "return_all_creatures_from_your_graveyard_to_battle
        field"}`` translates to a
        ``ReturnAllCreaturesFromYourGraveyardToBattlefield()``
        instance with ``creature=True``, ``destination='battlefield'``,
        ``untargeted_all=True`` (pinned by ``__post_init__``).
      * The Enchantment's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * ``requires_target() is False`` (the ``untargeted_all=True``
        pin makes this a mass-recursion sweep with no target slot).
      * With p0's graveyard EMPTY, the resolve is a no-op: log
        unchanged, battlefield unchanged, graveyard unchanged.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.graveyard import (
        ReturnAllCreaturesFromYourGraveyardToBattlefield,
        ReturnCreatureFromYourGraveyardToBattlefield,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Funeral Room // Awakening Hall
    #    printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get(
        "Funeral Room // Awakening Hall"
    )
    if real is None:
        pytest.skip(
            "Funeral Room // Awakening Hall absent from active CardSource"
        )
    assert "Enchantment" in real.card_types, (
        "Funeral Room // Awakening Hall must be an Enchantment"
    )
    assert "Room" in real.subtypes, (
        "Funeral Room // Awakening Hall must have the Room subtype"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
            and isinstance(
                ta.effect, ReturnAllCreaturesFromYourGraveyardToBattlefield,
            )
        ),
        None,
    )
    assert enters_ta is not None, (
        "Funeral Room // Awakening Hall must have an ENTERS triggered "
        "ability emitting ReturnAllCreaturesFromYourGraveyardToBattle"
        "field (the Awakening Hall back-half door body)"
    )
    # Awakening Hall is the back-half / second-unlocked face per the
    # Room subsystem convention (the door-half firing semantics stay
    # subsystem-deferred; this probe pins only the bare Effect+bridge+
    # resolve emission, NOT the full Room unlock lifecycle).
    assert getattr(enters_ta, "room_half", None) == "Awakening Hall", (
        f"Funeral Room // Awakening Hall's "
        f"ReturnAllCreaturesFromYourGraveyardToBattlefield trigger "
        f"must be attributed to the Awakening Hall back-half; got "
        f"room_half={getattr(enters_ta, 'room_half', None)!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "return_all_creatures_from_your_graveyard_to_battlefield"}
    )
    assert isinstance(
        bridged, ReturnAllCreaturesFromYourGraveyardToBattlefield,
    ), (
        f"Bridge arm "
        f"'return_all_creatures_from_your_graveyard_to_battlefield' "
        f"must round-trip to "
        f"ReturnAllCreaturesFromYourGraveyardToBattlefield; got "
        f"{type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Funeral Room // Awakening Hall ENTERS effect must be byte-"
        f"equal to the bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    # ReturnCreatureFromYourGraveyardToBattlefield is the TARGETED
    # single-card sister; ReturnAllCreaturesFromYourGraveyardToBattlefield
    # is the UNTARGETED mass-recursion sweep.  Both share the
    # ReturnFromGraveyard base but have distinct ``untargeted_all``
    # pins via __post_init__.
    assert bridged.untargeted_all is True, (
        "ReturnAllCreaturesFromYourGraveyardToBattlefield must have "
        "untargeted_all=True (the mass-recursion sweep pin)"
    )
    assert bridged.destination == "battlefield", (
        f"ReturnAllCreaturesFromYourGraveyardToBattlefield must have "
        f"destination='battlefield' (the mass-reanimation move target); "
        f"got destination={bridged.destination!r}"
    )
    assert bridged.creature is True, (
        "ReturnAllCreaturesFromYourGraveyardToBattlefield must have "
        "creature=True (the primary-type filter pin)"
    )
    assert bridged.requires_target() is False, (
        "ReturnAllCreaturesFromYourGraveyardToBattlefield must NOT "
        "require a target (the untargeted-all sweep iterates the "
        "entire graveyard; no player-chosen target slot)"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: empty-
    #    graveyard silent-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat Funeral Room // Awakening Hall on p0's battlefield.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Pre-resolve sanity: p0's graveyard is empty.
    assert len(py.players[0].graveyard) == 0, (
        "Pre-resolve sanity: p0's graveyard must be empty for the "
        "silent-no-op probe"
    )

    py.resolving_source = source
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)
    p0_gy_before = list(py.players[0].graveyard)
    p0_hand_before = list(py.players[0].hand)

    # ------------------------------------------------------------------
    # 5. resolve: empty-graveyard silent-no-op.  The ``_resolve_all``
    #    sweep at graveyard.py:244-257 collects ``cards = []`` when
    #    the graveyard is empty, the for-loop iterates zero times,
    #    leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Funeral Room // Awakening Hall: empty-graveyard resolve "
        f"must NOT append a log line (the ``_resolve_all`` empty-"
        f"sweep short-circuit at graveyard.py:244-257); got "
        f"log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Funeral Room // Awakening Hall: empty-graveyard resolve "
        "must NOT mutate the battlefield"
    )
    assert py.players[0].graveyard == p0_gy_before, (
        "Funeral Room // Awakening Hall: empty-graveyard resolve "
        "must NOT mutate the controller's graveyard (no cards to "
        "iterate)"
    )
    assert py.players[0].hand == p0_hand_before, (
        "Funeral Room // Awakening Hall: empty-graveyard resolve "
        "must NOT mutate the controller's hand (destination is "
        "battlefield, not hand)"
    )
    assert source in py.battlefield, (
        "Funeral Room // Awakening Hall: source must remain on the "
        "battlefield post-resolve"
    )

    py.resolving_source = None


# ---------------------------------------------------------------------------
# Probe 2 -- Moldering Gym // Weight Room: Enchantment (Room) ENTERS
#   triggered -> SearchLibraryForBasicLandTapped(count=1).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Moldering Gym //
#      Weight Room")`` returns the parsed CardPrinting (Enchantment,
#      Room).
#   2. The ENTERS triggered ability's effect (on the Moldering Gym
#      front-half, ``room_half='Moldering Gym'``) is a
#      ``SearchLibraryForBasicLandTapped(count=1)`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``SearchLibraryForBasicLandTapped(count=1)`` instance.
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against effect-class collapse to the
#      ``SearchLibraryForCard`` sister with different filter
#      taxonomy).
#   5. Python's ``resolve`` path with empty library is a controlled
#      log-one-line + shuffle no-op (the empty-library no-match
#      branch at ``effects/generic/search.py``:174-183 -- appends
#      one "no more basic lands" log line, then shuffles the empty
#      library which is itself a no-op).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_moldering_gym_parity():
    """**GENUINE real-EoE cross-engine probe -- Moldering Gym //
    Weight Room (round 36 JJJJ, Enchantment (Room) ENTERS ->
    SearchLibraryForBasicLandTapped(count=1)).**

    Drives the **real parsed Moldering Gym // Weight Room printing**
    through the Python-side ``SearchLibraryForBasicLandTapped``
    resolve path, validating the empty-library + shuffle-only
    short-circuit (the resolve's empty-library no-match branch at
    ``effects/generic/search.py``:174-183 -- appends one "no more
    basic lands" log line, then calls ``shuffle_library`` which is
    a no-op on an empty list per CR 701.19 / 701.22).  Pairs the
    parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD +
    EEEE + FFFF + GGGG + HHHH + IIII established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the bare unwrapped ``SearchLibraryForBasicLandTapped(count=1)``
    shape on a triggered-ability carrier.  Complements:
      * Larval Scoutlander is the known consumer of the WRAPPED
        shape (``OptionalSacArtifactForEffect`` outer with
        ``SearchLibraryForBasicLandTapped(count=2)`` inner per the
        bridge docstring at ``cross_engine.py``:3933-3948) -- a
        different carrier shape, different ``count``
        parameterization, and the may-sac wrapper drives an
        asymmetric agent shim path the bare slice does not
        exercise.
      * The IIII batch's The Seriema probe pins the sister
        ``SearchLibraryForCard`` arm with a different filter
        (``legendary_creature``); JJJJ pins the basic-land filter
        variant.  Distinct effect classes (the basic-land tapped
        ETB-with-summoning-sick-clearing per the round-54 fix at
        search.py:185-197 is its own resolve path).

    **Bridge arm exercised:**
    ``search_library_for_basic_land_tapped`` (matching Rust's
    ``Effect::SearchLibraryForBasicLandTapped { count }`` -- round 21
    BLOCKED-BRIDGE-ARM slice; bridge dispatch at
    ``cross_engine.py``:3902-3972).

    **Setup (Python-side):**
      * p0 has Moldering Gym // Weight Room on the battlefield;
        p0's library is EMPTY (the no-match shuffle-only case the
        probe verifies -- production library-non-empty fetches
        require basic lands in the library, gated by the broader
        deck-construction harness, separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "search_library_for_basic_land_tapped", "count":
        1}`` translates to a ``SearchLibraryForBasicLandTapped(
        count=1)`` instance.
      * The Enchantment's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * With p0's library EMPTY, the resolve appends ONE log line
        (the "no more basic lands" diagnostic) and calls
        ``shuffle_library`` (a no-op on empty); hand stays empty,
        library stays empty, battlefield stays unchanged.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped, SearchLibraryForCard,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Moldering Gym // Weight Room
    #    printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get(
        "Moldering Gym // Weight Room"
    )
    if real is None:
        pytest.skip(
            "Moldering Gym // Weight Room absent from active CardSource"
        )
    assert "Enchantment" in real.card_types, (
        "Moldering Gym // Weight Room must be an Enchantment"
    )
    assert "Room" in real.subtypes, (
        "Moldering Gym // Weight Room must have the Room subtype"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
            and isinstance(ta.effect, SearchLibraryForBasicLandTapped)
        ),
        None,
    )
    assert enters_ta is not None, (
        "Moldering Gym // Weight Room must have an ENTERS triggered "
        "ability emitting SearchLibraryForBasicLandTapped (the "
        "Moldering Gym front-half door body)"
    )
    # Moldering Gym is the front-half / first-unlocked face per the
    # Room subsystem convention.  This probe pins only the bare
    # Effect+bridge+resolve emission; the Room subsystem (unlock,
    # cycle, door-half firing semantics) stays deferred.
    assert getattr(enters_ta, "room_half", None) == "Moldering Gym", (
        f"Moldering Gym // Weight Room's "
        f"SearchLibraryForBasicLandTapped trigger must be attributed "
        f"to the Moldering Gym front-half; got "
        f"room_half={getattr(enters_ta, 'room_half', None)!r}"
    )
    # Pin the specific parameterization (the load-bearing "this card
    # carries THIS shape" assertion).
    assert enters_ta.effect.count == 1, (
        f"Moldering Gym ENTERS effect must have count=1; got "
        f"{enters_ta.effect.count}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "search_library_for_basic_land_tapped", "count": 1}
    )
    assert isinstance(bridged, SearchLibraryForBasicLandTapped), (
        f"Bridge arm 'search_library_for_basic_land_tapped' must "
        f"round-trip to SearchLibraryForBasicLandTapped; got "
        f"{type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Moldering Gym ENTERS effect must be byte-equal to the "
        f"bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, SearchLibraryForCard), (
        "SearchLibraryForBasicLandTapped must NOT collapse to "
        "SearchLibraryForCard (the sister library-search effect "
        "class for tutor-shape fetching to hand; "
        "SearchLibraryForBasicLandTapped fetches basic lands to the "
        "battlefield tapped, a structurally distinct primitive)."
    )
    # Round-trip an alternative count to ensure count is genuinely
    # round-tripped (not stripped or defaulted).
    other = _ta_dict_to_python_effect(
        {"kind": "search_library_for_basic_land_tapped", "count": 2}
    )
    assert other.count == 2, (
        f"Sibling round-trip must preserve count=2 (the Larval "
        f"Scoutlander OptionalSac-wrapped shape's count); got "
        f"{other.count}"
    )
    assert bridged != other, (
        "Moldering Gym's count=1 shape must NOT collapse to the "
        "count=2 Larval Scoutlander OptionalSac-wrapped shape"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: empty-
    #    library log-one-line + shuffle-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat Moldering Gym // Weight Room on p0's battlefield.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    assert len(py.players[0].library) == 0, (
        "Pre-resolve sanity: p0's library must be empty for the "
        "empty-library probe"
    )
    assert len(py.players[0].hand) == 0, (
        "Pre-resolve sanity: p0's hand must be empty"
    )

    py.resolving_source = source
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)
    p0_lib_before = list(py.players[0].library)
    p0_hand_before = list(py.players[0].hand)

    # ------------------------------------------------------------------
    # 5. resolve: empty-library log-one-line + shuffle path.  The
    #    resolve's empty-library no-match branch at search.py:174-183
    #    appends one log diagnostic ("no more basic lands") + calls
    #    shuffle_library (a no-op on empty list per CR 701.19/701.22).
    #    Hand stays empty, library stays empty, battlefield stays
    #    unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    # Exactly ONE log line appended (the "no more basic lands"
    # diagnostic).  This is the load-bearing observable distinct from
    # the no-op probes -- byte-equality includes log emission.
    assert len(py.log) == pre_log_len + 1, (
        f"Moldering Gym: empty-library resolve must append exactly "
        f"ONE log line (the 'no more basic lands' diagnostic at "
        f"search.py:175-177); got log_len={len(py.log)} (expected "
        f"{pre_log_len + 1})"
    )
    assert "no more basic lands" in py.log[-1], (
        f"Moldering Gym: empty-library log message must mention "
        f"'no more basic lands'; got {py.log[-1]!r}"
    )
    assert py.battlefield == bf_before, (
        "Moldering Gym: empty-library resolve must NOT mutate the "
        "battlefield"
    )
    assert py.players[0].hand == p0_hand_before, (
        "Moldering Gym: empty-library resolve must NOT add cards to "
        "the controller's hand (no options to fetch + destination is "
        "battlefield tapped not hand)"
    )
    assert py.players[0].library == p0_lib_before, (
        "Moldering Gym: empty-library resolve must NOT mutate the "
        "library (shuffle is a no-op on empty)"
    )
    assert source in py.battlefield, (
        "Moldering Gym: source must remain on the battlefield "
        "post-resolve"
    )

    py.resolving_source = None


# ---------------------------------------------------------------------------
# Probe 3 -- Surgical Suite // Hospital Room: Enchantment (Room)
#   YOU_ATTACK triggered -> PutPlusOneCounterOnTargetCreature(amount=1,
#   attacking_only=True).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Surgical Suite //
#      Hospital Room")`` returns the parsed CardPrinting (Enchantment,
#      Room).
#   2. The YOU_ATTACK triggered ability's effect (on the Hospital
#      Room back-half, ``room_half='Hospital Room'``) is a
#      ``PutPlusOneCounterOnTargetCreature(amount=1,
#      attacking_only=True)`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``PutPlusOneCounterOnTargetCreature(amount=1, attacking_only
#      =True)`` instance.
#   4. Distinctness from sibling parameterizations is preserved
#      (regression guard against attacking_only=True / False
#      collapse).
#   5. Python's ``resolve`` path with empty targets is a silent
#      no-op (the empty-targets short-circuit at
#      ``effects/generic/counters.py``:54-55; ``if not targets:
#      return``).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_surgical_suite_parity():
    """**GENUINE real-EoE cross-engine probe -- Surgical Suite //
    Hospital Room (round 36 JJJJ, Enchantment (Room) YOU_ATTACK ->
    PutPlusOneCounterOnTargetCreature(amount=1,
    attacking_only=True)).**

    Drives the **real parsed Surgical Suite // Hospital Room
    printing** through the Python-side
    ``PutPlusOneCounterOnTargetCreature`` resolve path, validating
    the empty-targets silent-no-op short-circuit (the resolve's
    empty-targets branch at ``effects/generic/counters.py``:54-55;
    ``if not targets: return``).  Pairs the parse + bridge round-
    trip verification with the live Python resolve smoke, the same
    parse + bridge-round-trip + Python-side resolve idiom DDD slice
    17 + YYY + ZZZ + AAAA + CCCC + DDDD + EEEE + FFFF + GGGG +
    HHHH + IIII established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding the ``attacking_only=True`` parameterization of the
    PutPlusOneCounterOnTargetCreature effect class on a YOU_ATTACK
    triggered-ability carrier on the REAL parsed EoE printing.
    Complements:
      * Drix Fatemaker (PROBED via the smoke-file probe) pins the
        bare ``PutPlusOneCounterOnTargetCreature(amount=1)`` shape
        on ENTERS with ``attacking_only=False`` (the default).
      * Mm'menon, Uthros Exile (PROBED) pins the same effect class
        with ``attacking_only=False``.
      * IIII's Optimistic Scavenger probe explicitly noted the
        ``attacking_only=True`` parameterization as a distinct
        axis ("Sibling round-trip must preserve attacking_only=True
        (the Hospital Room half shape)" at
        ``tests/test_probe_remaining_iiii.py``:972) and USED
        Hospital Room as the contrast carrier for that distinctness
        assertion -- JJJJ now pins Hospital Room directly with the
        credited ``_parity`` probe, closing the attribution gap
        that the IIII contrast assertion implicitly named.
      * Honor (PROBED) drives the same effect class as a SPELL --
        DIFFERENT event with ``attacking_only=False``.
    The PROBED-tier classifier credits per-slug; Surgical Suite //
    Hospital Room is currently covered-by-construction but has no
    slug-keyed probe -- JJJJ closes the attribution gap.

    **Bridge arm exercised:**
    ``put_plus_one_counter_on_target_creature`` (matching Rust's
    ``Effect::PutPlusOneCounterOnTargetCreature { amount,
    attacking_only }`` -- PPP Pin 2 / 10th Rust slice; bridge
    dispatch at ``cross_engine.py``:9542-9591).

    **Setup (Python-side):**
      * p0 has Surgical Suite // Hospital Room on the battlefield;
        no other creatures (the empty-targets case the probe
        verifies -- production target-bearing cases are gated by
        the agent target-picker substrate, separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "put_plus_one_counter_on_target_creature",
        "amount": 1, "attacking_only": True}`` translates to a
        ``PutPlusOneCounterOnTargetCreature(amount=1,
        attacking_only=True)`` instance.
      * The Enchantment's YOU_ATTACK triggered ability emits the
        same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * ``requires_target() is True`` (the oracle "target attacking
        creature").
      * With empty targets, the resolve is a no-op: log unchanged,
        battlefield unchanged, source remains on bf.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnTargetCreature, PutPlusOneCounterOnSelf,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Surgical Suite // Hospital Room
    #    printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get(
        "Surgical Suite // Hospital Room"
    )
    if real is None:
        pytest.skip(
            "Surgical Suite // Hospital Room absent from active "
            "CardSource"
        )
    assert "Enchantment" in real.card_types, (
        "Surgical Suite // Hospital Room must be an Enchantment"
    )
    assert "Room" in real.subtypes, (
        "Surgical Suite // Hospital Room must have the Room subtype"
    )
    you_attack_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.YOU_ATTACK
            and isinstance(ta.effect, PutPlusOneCounterOnTargetCreature)
        ),
        None,
    )
    assert you_attack_ta is not None, (
        "Surgical Suite // Hospital Room must have a YOU_ATTACK "
        "triggered ability emitting PutPlusOneCounterOnTargetCreature "
        "(the Hospital Room back-half door body)"
    )
    # Hospital Room is the back-half / second-unlocked face per the
    # Room subsystem convention.  This probe pins only the bare
    # Effect+bridge+resolve emission; the Room subsystem (unlock,
    # cycle, door-half firing semantics) stays deferred.
    assert getattr(you_attack_ta, "room_half", None) == "Hospital Room", (
        f"Surgical Suite // Hospital Room's "
        f"PutPlusOneCounterOnTargetCreature trigger must be attributed "
        f"to the Hospital Room back-half; got "
        f"room_half={getattr(you_attack_ta, 'room_half', None)!r}"
    )
    # Pin the specific parameterization.
    assert you_attack_ta.effect.amount == 1, (
        f"Surgical Suite // Hospital Room YOU_ATTACK effect must "
        f"have amount=1; got {you_attack_ta.effect.amount}"
    )
    assert you_attack_ta.effect.attacking_only is True, (
        f"Surgical Suite // Hospital Room YOU_ATTACK effect must "
        f"have attacking_only=True (the Hospital Room parameterization "
        f"distinct from the Optimistic Scavenger / Drix Fatemaker / "
        f"Mm'menon Uthros Exile attacking_only=False half); got "
        f"{you_attack_ta.effect.attacking_only}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_target_creature",
            "amount": 1,
            "attacking_only": True,
        }
    )
    assert isinstance(bridged, PutPlusOneCounterOnTargetCreature), (
        f"Bridge arm 'put_plus_one_counter_on_target_creature' must "
        f"round-trip to PutPlusOneCounterOnTargetCreature; got "
        f"{type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert you_attack_ta.effect == bridged, (
        f"Surgical Suite // Hospital Room YOU_ATTACK effect must be "
        f"byte-equal to the bridged Effect; got "
        f"parsed={you_attack_ta.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes / parameterizations
    #    (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, PutPlusOneCounterOnSelf), (
        "PutPlusOneCounterOnTargetCreature must NOT collapse to "
        "PutPlusOneCounterOnSelf (the sibling self-targeted counter "
        "effect; different targeting -- self vs target creature)."
    )
    # Distinctness from the attacking_only=False shape that IIII's
    # Optimistic Scavenger / Drix Fatemaker / Mm'menon Uthros Exile
    # pin -- the load-bearing distinctness assertion that makes this
    # a NEW shape, not a duplicate of IIII's Optimistic Scavenger.
    non_attacking_variant = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_target_creature",
            "amount": 1,
        }
    )
    assert non_attacking_variant.attacking_only is False, (
        "Sibling round-trip must preserve attacking_only=False (the "
        "default; the Optimistic Scavenger / Drix Fatemaker shape)"
    )
    assert bridged != non_attacking_variant, (
        "Surgical Suite // Hospital Room's (amount=1, "
        "attacking_only=True) shape must NOT collapse to Optimistic "
        "Scavenger / Drix Fatemaker's (amount=1, attacking_only="
        "False) shape"
    )
    assert bridged.requires_target() is True, (
        "PutPlusOneCounterOnTargetCreature must require a target "
        "(the oracle 'target attacking creature')"
    )
    assert bridged.target_count_range() == (1, 1), (
        f"PutPlusOneCounterOnTargetCreature must have "
        f"target_count_range=(1, 1); got "
        f"{bridged.target_count_range()}"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: empty-
    #    targets silent-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat Surgical Suite // Hospital Room on p0's battlefield.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    py.resolving_source = source
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)
    source_counters_before = source.plus_one_counters

    # ------------------------------------------------------------------
    # 5. resolve: empty-targets silent-no-op.  The resolve's empty-
    #    targets branch at counters.py:54-55 (``if not targets:
    #    return``) leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Surgical Suite // Hospital Room: empty-targets resolve "
        f"must NOT append a log line (the resolve's empty-targets "
        f"short-circuit at counters.py:54-55); got "
        f"log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Surgical Suite // Hospital Room: empty-targets resolve "
        "must NOT mutate the battlefield"
    )
    assert source.plus_one_counters == source_counters_before, (
        f"Surgical Suite // Hospital Room: empty-targets resolve "
        f"must NOT add +1/+1 counters to the source; got "
        f"counters={source.plus_one_counters} (expected "
        f"{source_counters_before})"
    )
    assert source in py.battlefield, (
        "Surgical Suite // Hospital Room: source must remain on the "
        "battlefield post-resolve"
    )

    py.resolving_source = None
