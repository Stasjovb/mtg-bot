"""Genuine real-EoE cross-engine byte-equality probes -- batch GGGG
(round 33, the SEVENTH 4-letter probe batch -- post-FFFF).

The AAAA batch (``tests/test_probe_remaining_aaaa.py``) opened the
4-letter naming convention post-ZZZ alphabetic exhaustion.  GGGG is
the seventh 4-letter batch (round 33); prior 4-letter batches are
AAAA (round 27), BBBB (round 28), CCCC (round 29), DDDD (round 30
reclaim, main HEAD ``8aeb70b4``), EEEE (round 31 reclaim, main HEAD
``04c1f16e``), and FFFF (round 32 relaunch, main HEAD ``25c0d410``).
Subsequent batches follow ``HHHH`` / ``IIII`` / ... per the
established 4-letter alphabetic cadence.

ONE card from the ``covered_by_construction`` tier is upgraded to
the ``PROBED`` tier by this module via the same parse + bridge round-
trip + Python-side resolve idiom DDD slice 17's Honored Knight-Captain
probe (``tests/test_probe_ddd_downstream.py``:408), the YYY batch's
two probes (``tests/test_probe_remaining_yyy.py``:272 / 573), the ZZZ
batch's two probes (``tests/test_probe_remaining_zzz.py``:173 / 413),
the AAAA batch's two probes (``tests/test_probe_remaining_aaaa.py``:231
/ 511), the CCCC batch's two probes
(``tests/test_probe_remaining_cccc.py``:223 / 430), the DDDD batch's
two probes (``tests/test_probe_remaining_dddd.py``:289 / 526), the
EEEE batch's two probes (``tests/test_probe_remaining_eeee.py``:245
/ 501), and the FFFF batch's single Illvoi Operative probe
(``tests/test_probe_remaining_ffff.py``) established as a
PROBE_MODULES-credited shape.

The originally-drafted GGGG batch carried TWO probes -- Illvoi
Operative (Creature IS_CAST -> PutPlusOneCounterOnSelf(amount=1))
and Roving Actuator (Artifact Creature ENTERS ->
RovingActuatorETBEffect(max_mv=2)).  The FFFF lane landed first
(main HEAD ``25c0d410``) and shipped Illvoi Operative under the same
EEEE-idiom (predicate-is-metadata gap-bypass).  The GGGG reclaim
drops the Illvoi Operative probe to avoid duplicate credit (the
PROBED-credit predicate is name+_parity function match; re-probing
Illvoi Operative would not move the classifier needle), keeping only
the Roving Actuator probe which FFFF did not claim.  Net delta:
+1 probe (Roving Actuator).

  * **Roving Actuator** -- Creature with an ENTERS triggered ability
    emitting ``RovingActuatorETBEffect(max_mv=2)`` (the dedicated
    bespoke effect for the Void ETB "Exile up to one target instant
    or sorcery card with mana value 2 or less from your graveyard.
    Copy it. You may cast the copy without paying its mana cost.").
    Bridge arm at ``cross_engine.py``: ``roving_actuator_etb``
    (matching Rust's ``Effect::RovingActuatorETBEffect { max_mv:
    u8 }`` -- the variant the 18th Rust slice / XXX Pin 2 added;
    ``tests/test_probe_xxx_downstream.py``).  **NEW shape coverage:**
    the FIRST credited ``_parity`` probe of this dedicated bespoke
    effect class.  Complements:
      * The XXX-slice closure tests at
        ``tests/test_probe_xxx_downstream.py``
        (``test_xxx_probe_roving_actuator_etb_*``,
        ``test_xxx_probe_roving_actuator_empty_filter_no_op``,
        ``test_xxx_probe_roving_actuator_mv_filter_excludes_high_mv_spell``)
        exercise the bridge round-trip + cross-engine resolve
        trajectory on a SYNTHETIC Roving-Actuator-shape carrier;
        they are NOT credited by the PROBED-tier classifier because
        the function names do not end ``_parity`` (they predate the
        naming convention).  GGGG lands the credited ``_parity``
        variant on the REAL parsed Roving Actuator EoE printing,
        which the existing tests do not bind via
        ``get_printings().get("Roving Actuator")`` (they synthesize
        the carrier via ``register_and_inject_object``).
    The bridge arm + the Python-side resolve are the same as the
    XXX-slice closure tests; what's NEW is the carrier substrate
    (the REAL parsed Roving Actuator EoE printing, not a synthetic
    shape) and the credited ``_parity`` naming convention the
    classifier scans for.

DROPPED ON VERIFY (honest discipline)
---------------------------------------------------------------------

  * **Meltstrider Eulogist** -- already PROBED via DDDD (round 30
    reclaim, main HEAD ``8aeb70b4``); FFFF (round 32 relaunch,
    in-flight sibling) also drafts this card.  Not re-probed here.

  * **Balemurk Leech** -- already PROBED via DDDD; not re-probed.

  * **Starwinder** / **Broodguard Elite** -- already PROBED via EEEE
    (round 31 reclaim, main HEAD ``04c1f16e``); not re-probed.

  * **Optimistic Scavenger** -- ENTERS + PutPlusOneCounterOnTarget
    Creature(amount=1); already PROBED via Drix Fatemaker
    (ENTERS-event, same bare effect class with amount=1) +
    ``Mm'menon, Uthros Exile`` (ENTERS-event, same effect class).
    The ROOM_FULLY_UNLOCKED-event leg is subsystem-gated (Rooms);
    out of scope for the bare effect+bridge+resolve idiom.  No NEW
    Effect+bridge axis coverage.

  * **Unwanted Remake / Come Back Wrong / Final Vengeance / Seized
    from Slumber** -- bare ``DestroyTargetCreature`` spell-effect,
    byte-identical to the already-PROBED Murder (``test_parity_
    smoke.py``).  No NEW Effect+bridge axis coverage -- same drop
    discipline as the prior batch-S / batch-P / batch-V drop lists.

  * **Weapons Manufacturing / Station Monitor** -- ENTERS /
    IS_CAST + ``CreateToken``; token-registration substrate
    requires seating the token ``CardPrinting`` via
    ``register_token_printing`` AND the bridge arm shape with the
    full nested token printing dict.  Same drop discipline as the
    EEEE Sami, Ship's Engineer drop note (token-creation substrate
    requires additional harness work beyond the bare
    effect+bridge slice).

  * **Pain for All / Tractor Beam** -- BLOCKED-genuinely_missing
    (Pain for All) / Aura-substrate-gated (Tractor Beam, Phase 2 in
    flight on ``feature/aura-substrate-phase-2``).  Out of scope per
    the lane coordination note.

  * **Clammy Prowler** (ATTACKS + GrantUnblockableUEOT): no matching
    ``grant_unblockable_ueot`` bridge arm in ``cross_engine.py``
    (verified via direct ``_ta_dict_to_python_effect`` smoke --
    raises ``unsupported effect kind 'grant_unblockable_ueot'``).
    Honest exhaustion at the bridge layer until a
    ``grant_unblockable_ueot`` bridge slice lands.

  * **Dawnsire, Sunstar Dreadnought** (YOU_ATTACK +
    DealDamageToTargetCreature(amount=100, optional=True)): no
    matching ``deal_damage_to_target_creature`` bridge arm
    (verified via direct ``_ta_dict_to_python_effect`` smoke --
    raises ``unsupported effect kind``).  Honest exhaustion at the
    bridge layer.

  * **Hand That Feeds / Flesh Burrower / Cult Healer** (pump
    triggers carrying a ``granted_keywords`` rider): the
    ``pump_self_until_eot`` bridge arm drops the ``granted_keywords``
    rider (verified: ``granted_keywords=['menace']`` round-trips to
    ``granted_keywords=frozenset()`` -- the rider is silently
    elided).  The byte-equality assertion the PROBED tier credits
    would therefore fail on these carriers.  Honest exhaustion
    until a rider-bearing pump arm lands -- same drop discipline as
    CCCC / EEEE / FFFF.

  * **Sami, Ship's Engineer** (BEGINNING_OF_END_STEP +
    ``ConditionalOnTappedCreatures(CreateToken(...))``): token-
    registration substrate + the ConditionalOnTappedCreatures
    wrapper substrate -- same deferral the EEEE / DDDD drop notes
    cover.

  * **Sunstar Lightsmith / Cosmogrand Zenith** (IS_CAST + Sequence /
    ModalChooseOne wrapper around bridged effects): the Sequence /
    Modal wrapper around two or more bridged effects raises the
    aggregation question -- the bare bridge dispatches per-effect,
    not on the Sequence / Modal container.  Deferred until a
    Sequence-level / Modal-level bridge slice lands -- same drop
    discipline as the EEEE Sunstar Lightsmith / Let's Play a Game
    drop notes.

  * **Conductive Machete / Cursed Windbreaker / Killer's Mask /
    Squire's Lightblade / Illvoi Light Jammer**: Equipment ETB +
    ``ManifestDreadThenAttachSelf`` -- the ManifestDread resolve
    substrate requires library + agent picker, same deferral
    AAAA / CCCC / EEEE / FFFF have applied.

  * **Break Down the Door / Under the Skin / Innocuous Rat /
    Unnerving Grasp / Moldering Gym // Weight Room / Underwater
    Tunnel // Slimy Aquarium** -- ManifestDread effect /
    ManifestDreadThenPutPlusOneCountersOnIt wrapper: same
    ManifestDread harness substrate deferral.

  * **Let's Play a Game / Split Up** (Sorcery
    ``spell_effect=ModalChooseOne``): modal-choice substrate
    requires an agent picker + mode-resolution wiring (same drop
    as CCCC / EEEE).

  * **Temporal Intervention** (Sorcery
    ``spell_effect=TargetOpponentDiscardsCasterChoice``): no
    matching ``target_opponent_discards_caster_choice`` bridge arm
    in ``cross_engine.py`` (verified via direct
    ``_ta_dict_to_python_effect`` smoke -- raises
    ``unsupported effect kind`` UnknownEffectKindError).  Honest
    exhaustion at the bridge layer -- same drop as EEEE.

  * **Vanilla / keyword-only creatures** (Bedhead Beastie, Cackling
    Slasher, Daggermaw Megalodon, Patched Plaything, Piranha Fly,
    Spectral Snatcher, Shepherding Spirits, Fear of Being Hunted,
    Slavering Branchsnapper, Ripchain Razorkin, Rust Harvester,
    Slagdrill Scrapper, Gene Pollinator, Steelswarm Operator,
    Fear of Failed Tests, Irreverent Gremlin -- to the extent
    they're not subsystem-gated): no triggered abilities, no
    spell_effect, only static keywords / activated abilities.
    Already represented by probed siblings; no NEW shape coverage.
    Same drop discipline as SSS / QQQ / UUU / WWW / YYY / EEEE /
    FFFF.

  * **Room cards** (Bottomless Pool // Locker Room / Funeral Room
    // Awakening Hall / Restricted Office // Lecture Hall / Mirror
    Room // Fractured Realm / Surgical Suite // Hospital Room /
    Grand Entryway // Elegant Rotunda / Underwater Tunnel // Slimy
    Aquarium / Moldering Gym // Weight Room / Ticket Booth //
    Tunnel of Hate / Derelict Attic // Widow's Walk): subsystem-
    gated by the Room substrate -- the parse + bridge round-trip
    portion would work for the bare ENTERS-event leg, but the
    ROOM_FULLY_UNLOCKED legs are out of scope, and the partial
    coverage (ENTERS only) does not pin the full card.  Honest
    exhaustion at the Room-substrate layer.

  * **Lithobraking / Give In to Violence / Dual-Sun Technique /
    Horrid Vigor / Rig for War / Violent Urge** (spell effects
    with Sequence wrappers / pump riders): aggregation /
    rider-omission deferrals same as the EEEE / FFFF drop notes.

  * **Lands** (Forest, Island, Mountain, Plains, Swamp + dual
    lands -- Blazemire Verge, Floodfarm Verge, Gloomlake Verge,
    Hushwood Verge, Thornspire Verge, Celestial Colonnade,
    Hissing Quagmire, Lumbering Falls, Needle Spires, Raging
    Ravine, Shambling Vent, Stirring Wildwood, Creeping Tar Pit
    + utility lands -- Cascading Cataracts, Command Bridge,
    Crystal Quarry, Dust Bowl, Eldrazi Temple, Gemstone Caverns,
    High Market, Inkmoth Nexus, Inventors' Fair, Mana Confluence,
    Mutavault, Plaza of Heroes, Power Depot, Sunken Citadel,
    Blinkmoth Nexus): basic lands and dual-land activated
    abilities -- no triggered abilities, no spell_effect.
    The bare-effect+bridge+resolve idiom does not pin these;
    they need an activated-ability probe surface, which is
    subsystem-gated (separate probe surface, not covered by the
    PROBED-tier ``_parity`` classifier).  Honest exhaustion at
    the activated-ability surface.

  * **All previously-PROBED cards** with the same effect classes --
    Banishing Light, Sheltered by Ghosts (ZZZ), Stay Hidden / Stay
    Silent (ZZZ), Hardlight Containment, Diplomatic Relations
    (YYY), Astelli Reclaimer (YYY), Cryoshatter / Meltstrider's
    Gear (AAAA), Withering Torment (BBBB), Lightless Evangel /
    Skystinger (CCCC), Meltstrider Eulogist / Balemurk Leech
    (DDDD), Starwinder / Broodguard Elite (EEEE) -- already
    PROBED via earlier modules; not re-probed here.

  * **Subsystem-gated remainder** -- the long tail of Aura
    attachment full surface / Equipment activated-ability surface /
    Room / IS_CAST stack-resolution / non-Effect gate cards / Land
    activated abilities; the EEEE-idiom (parse + bridge + Python-
    resolve) does not unblock them.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
ONE card moves from ``covered_by_construction`` to the ``PROBED``
tier upon merge.  Prior PROBED count (with AAAA + BBBB + CCCC + DDDD
+ EEEE + FFFF wired in via PROBE_MODULES, post-FFFF merge -- main
HEAD ``25c0d410``): 229.  Net delta from this module: +1 (PROBED),
-1 (covered).  The originally-drafted GGGG carried two probes; the
FFFF lane (round 32 relaunch) landed first on main and credited
Illvoi Operative, so the GGGG reclaim drops the Illvoi Operative
probe (honest-exhaustion: duplicate credit would not move the
classifier needle) and keeps only the Roving Actuator probe.
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
# Probe 1 -- Roving Actuator: Creature ENTERS triggered ->
#   RovingActuatorETBEffect(max_mv=2).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Roving Actuator")``
#      returns the parsed CardPrinting (Artifact Creature, Robot).
#   2. The ENTERS triggered ability's effect is a
#      ``RovingActuatorETBEffect(max_mv=2)`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``RovingActuatorETBEffect(max_mv=2)`` instance.
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against effect-class collapse).
#   5. Python's ``resolve`` path on an empty-graveyard state is a
#      no-op (the empty-target short-circuit at bespoke.py:667-668);
#      the source remains on the battlefield with no state mutation.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_roving_actuator_parity():
    """**GENUINE real-EoE cross-engine probe -- Roving Actuator
    (round 33 GGGG, Creature ENTERS ->
    RovingActuatorETBEffect(max_mv=2)).**

    Drives the **real parsed Roving Actuator printing** through the
    Python-side ``RovingActuatorETBEffect`` resolve path, validating
    the empty-target short-circuit (an empty graveyard yields zero
    legal targets, the resolve's targets=() early-return at
    ``bespoke.py``:667-668 leaves state unchanged).  Pairs the parse
    + bridge round-trip verification with the live Python resolve
    smoke, the same parse + bridge-round-trip + Python-side resolve
    idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD + EEEE + FFFF
    established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the dedicated bespoke ``RovingActuatorETBEffect`` effect class
    on the REAL parsed Roving Actuator EoE printing.  Complements:
      * The XXX-slice closure tests at
        ``tests/test_probe_xxx_downstream.py``
        (``test_xxx_probe_roving_actuator_*``) which exercise the
        bridge round-trip + cross-engine resolve trajectory on a
        SYNTHETIC Roving-Actuator-shape carrier (the tests use
        ``register_and_inject_object`` to build the carrier; they
        do NOT bind the real parsed printing via
        ``get_printings().get("Roving Actuator")``).  Those tests
        are NOT credited by the PROBED-tier classifier because
        their function names do not end ``_parity`` (they predate
        the naming convention).  GGGG lands the credited
        ``_parity`` variant on the REAL parsed printing.

    **Bridge arm exercised:**
    ``roving_actuator_etb`` (matching Rust's
    ``Effect::RovingActuatorETBEffect { max_mv: u8 }`` -- the
    18th Rust slice / XXX Pin 2 variant; bridge dispatch at
    ``cross_engine.py`` in the ``_ta_dict_to_python_effect``
    bespoke-arm section).

    **Setup (Python-side):**
      * p0 has Roving Actuator on the battlefield (the Creature
        serving as ``resolving_source``).
      * p0's graveyard is empty (the empty-target short-circuit
        case the probe verifies -- the resolve's targets=()
        early-return at ``bespoke.py``:667-668).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "roving_actuator_etb", "max_mv": 2}`` translates
        to a ``RovingActuatorETBEffect(max_mv=2)`` instance.
      * The Creature's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Empty graveyard => legal_targets returns []; the resolve
        called with targets=() is a no-op (state unchanged, no
        log lines added, source remains on battlefield).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import RovingActuatorETBEffect
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Roving Actuator printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Roving Actuator")
    )
    if real is None:
        pytest.skip("Roving Actuator absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Roving Actuator must be a Creature"
    )
    assert "Artifact" in real.card_types, (
        "Roving Actuator must be an Artifact (Artifact Creature -- "
        "the carrier substrate distinguishing this card from the "
        "pure-Creature PROBED siblings)"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Roving Actuator must have an ENTERS triggered ability "
        "(the Void ETB the bespoke RovingActuatorETBEffect class "
        "encodes)"
    )
    assert isinstance(
        enters_ta.effect, RovingActuatorETBEffect,
    ), (
        f"Roving Actuator ENTERS effect must be "
        f"RovingActuatorETBEffect; got "
        f"{type(enters_ta.effect).__name__}"
    )
    assert enters_ta.effect.max_mv == 2, (
        f"Roving Actuator ENTERS effect must have max_mv=2 (the "
        f"oracle text 'mana value 2 or less'); got "
        f"max_mv={enters_ta.effect.max_mv}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "roving_actuator_etb", "max_mv": 2}
    )
    assert isinstance(bridged, RovingActuatorETBEffect), (
        f"Bridge arm 'roving_actuator_etb' must round-trip to "
        f"RovingActuatorETBEffect; got {type(bridged).__name__}"
    )
    assert bridged.max_mv == 2, (
        f"Bridge round-trip must preserve max_mv=2; got "
        f"max_mv={bridged.max_mv}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Roving Actuator ENTERS effect must be byte-equal to the "
        f"bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, PutPlusOneCounterOnSelf), (
        "RovingActuatorETBEffect must NOT collapse to "
        "PutPlusOneCounterOnSelf (a sibling bare counter-mutation "
        "effect class; RovingActuator's resolve exiles + copies + "
        "casts an instant/sorcery from gy, PutPlusOneCounterOnSelf "
        "writes to source.plus_one_counters)."
    )
    # RovingActuatorETBEffect requires a target.
    assert bridged.requires_target() is True, (
        "RovingActuatorETBEffect must require a target (its resolve "
        "dereferences targets[0] for the graveyard-spell pick)"
    )
    # And the target-count range matches the oracle "up to one".
    assert bridged.target_count_range() == (0, 1), (
        f"RovingActuatorETBEffect must have target_count_range=(0, 1) "
        f"(the oracle 'up to one'); got "
        f"{bridged.target_count_range()}"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: empty
    #    graveyard yields the empty-target short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Roving Actuator Creature on p0's battlefield.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    p0 = py.players[0]
    assert len(p0.graveyard) == 0, (
        f"Pre-resolve sanity: p0 graveyard must be empty for the "
        f"empty-target short-circuit probe; got "
        f"len={len(p0.graveyard)}"
    )

    # legal_targets must return [] on an empty graveyard (the resolve's
    # filter at bespoke.py:653-659 walks p0.graveyard).
    legal = bridged.legal_targets(py, controller_id=0)
    assert legal == [], (
        f"Roving Actuator: legal_targets must return [] on an empty "
        f"graveyard; got {legal}"
    )

    # ------------------------------------------------------------------
    # 5. resolve: targets=() empty-target short-circuit -- the
    #    resolve's early-return at bespoke.py:667-668 leaves state
    #    unchanged.
    # ------------------------------------------------------------------
    py.resolving_source = source
    pre_log_len = len(py.log)
    p0_bf_before = list(py.battlefield)
    p0_gy_before = list(p0.graveyard)
    p0_exile_before = list(p0.exile)

    bridged.resolve(py, controller_id=0, targets=())

    # No log lines added (the resolve early-returned before the
    # "exiles ... and copies it" log line at bespoke.py:680-682).
    assert len(py.log) == pre_log_len, (
        f"Roving Actuator: empty-target resolve must NOT append a "
        f"log line (the resolve's empty-target early-return at "
        f"bespoke.py:667-668); got log_len={len(py.log)} (expected "
        f"{pre_log_len})"
    )
    # Battlefield unchanged.
    assert py.battlefield == p0_bf_before, (
        "Roving Actuator: empty-target resolve must NOT mutate the "
        "battlefield (no card moved to exile, no copy resolved)"
    )
    # Graveyard unchanged (still empty).
    assert p0.graveyard == p0_gy_before, (
        "Roving Actuator: empty-target resolve must NOT mutate p0's "
        "graveyard (no card exiled)"
    )
    # Exile unchanged.
    assert p0.exile == p0_exile_before, (
        "Roving Actuator: empty-target resolve must NOT mutate p0's "
        "exile (no card moved to exile)"
    )
    # Source remains on the battlefield.
    assert source in py.battlefield, (
        "Roving Actuator: source must remain on the battlefield "
        "post-resolve (the Void ETB does NOT relocate itself even "
        "when its effect is a no-op)"
    )

    py.resolving_source = None
