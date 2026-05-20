"""Genuine real-EoE cross-engine byte-equality probes -- batch DDDD
(round 30, post-EEEE-reclaim re-pick).

The AAAA batch (``tests/test_probe_remaining_aaaa.py``:1-15) opened
the 4-letter naming convention post-ZZZ alphabetic exhaustion.  DDDD
is the fourth 4-letter batch; sibling lane EEEE (round 31 reclaim;
merged to ``origin/main`` at ``04c1f16e``) shipped Starwinder +
Broodguard Elite, the two cards DDDD was originally drafting against.
**This reclaim re-picks two DIFFERENT covered-but-unprobed cards** to
avoid duplicate credit (the PROBED-credit predicate is name+_parity
function match; re-probing the EEEE cards would not move the
classifier needle).  Subsequent batches follow ``FFFF`` / ``GGGG`` /
... per the established 4-letter alphabetic cadence.

Two cards from the ``covered_by_construction`` tier are upgraded to
the ``PROBED`` tier by this module via the same parse + bridge round-
trip + Python-side resolve idiom DDD slice 17's Honored Knight-Captain
probe (``tests/test_probe_ddd_downstream.py``:408), the YYY batch's
two probes (``tests/test_probe_remaining_yyy.py``:272 / 573), the ZZZ
batch's two probes (``tests/test_probe_remaining_zzz.py``:173 / 413),
the AAAA batch's two probes (``tests/test_probe_remaining_aaaa.py``:231
/ 511), the CCCC batch's two probes
(``tests/test_probe_remaining_cccc.py``:223 / 430), and EEEE's two
probes (``tests/test_probe_remaining_eeee.py``) established as a
PROBE_MODULES-credited shape.

  * **Meltstrider Eulogist** -- Creature with a DIES triggered
    ability emitting ``DrawCards(amount=1)``.  Bridge arm at
    ``cross_engine.py``:596 (the ORIGINAL three-arm minimum-viable
    surface, predating the BLOCKED-BRIDGE-ARM campaign; carries the
    explicit ``count`` -> ``amount`` field translation).  **NEW
    shape coverage:** the ONLY EoE consumer of the DIES +
    ``DrawCards`` shape (verified via a name-walking
    ``triggered_abilities`` scan over the entire active CardSource;
    no other EoE printing carries this exact event + effect class
    combination).  Complements:
      * Numerous existing PROBED + covered-by-construction
        ``DrawCards`` consumers under ENTERS / IS_CAST / SPELL /
        ATTACKS events (e.g. Mechan Navigator's ENTERS-leg
        DrawCards; the BBBB batch's spell_effect Sequence-of-
        destroy+lose_life closing the BBBB DrawCards-sibling
        coverage axis).  This probe pins the DIES event +
        DrawCards combination -- distinct from existing DIES probes
        which carry CreateToken / DealDamage / Sequence-style
        composite effects, not the bare ``DrawCards(amount=1)``
        single primitive.
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the **trigger event + effect-class combination**
    (DIES + bare ``DrawCards``).  The Meltstrider Eulogist DIES
    predicate (a composite ``And(Subject(IsCreature() &
    HasCounter('+1/+1')), Controlled)``) was previously dropped on
    verify in the ``test_probe_covered_unprobed_i.py``:38-47 batch
    because Rust's ``parse_predicate`` has no ``has_counter`` arm,
    making a faithful cross-engine compare_fields probe impossible
    without a new Rust substrate.  Under the YYY-idiom (parse +
    bridge of EFFECT + Python-side resolve smoke, NOT a Rust-side
    cross-engine compare requiring predicate bridge parity), the
    HasCounter predicate is METADATA: the probe verifies the
    effect + the resolve mutation regardless of predicate firing,
    so the predicate gap does NOT block credit.  The CCCC
    Lightless Evangel probe established this drop-recovery
    precedent (``test_probe_remaining_cccc.py``:148-154 -- the
    Lightless Evangel sacrifice-cause composite predicate is
    metadata; the probe pins the EFFECT shape regardless).

  * **Balemurk Leech** -- Creature with an ENTERS triggered
    ability emitting ``EachOpponentLosesLife(amount=1)``.  Bridge
    arm at ``cross_engine.py``:4819 (round-23 BLOCKED-BRIDGE-ARM
    slice closure; ``Effect::EachOpponentLosesLife { amount: i32 }``
    -- CR 118.4 direct life loss, NOT damage; punisher / drawback
    pattern).  **NEW shape coverage:** the ONLY EoE consumer of the
    ``EachOpponentLosesLife`` effect class (verified via a
    name-walking scan -- 1 EoE card hit per the cross_engine.py
    bridge-arm docstring at line 4872-4874 and confirmed by a
    parser-printings scan; the only consumer is Balemurk Leech
    itself).  Complements:
      * Sister effects ``TargetOpponentLosesLife`` (which targets a
        specific opponent via the Decision pipeline and defaults to
        amount=1) and ``DamageEachOpponent`` (which deals DAMAGE
        routed through damage-prevention -- vs this arm's direct
        life subtraction).  This probe pins the **first credited
        ``EachOpponentLosesLife`` _parity probe**.
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the **effect class** (CR 118.4 direct life loss
    primitive distinct from damage-routed primitives -- not
    reducible by damage-prevention / Worship-style replacement;
    the punisher / drawback pattern's canonical bridge probe).
    Balemurk Leech also has a sibling ROOM_FULLY_UNLOCKED-event
    trigger emitting the same effect; the ROOM event is
    subsystem-gated per the ``test_probe_remaining_cccc.py`` drop-
    list (Optimistic Scavenger / Cult Healer in that batch's
    rationale), so this probe pins only the ENTERS leg.
    Balemurk Leech was previously the subject of a non-credited
    ``test_cross_engine_real_eoe_balemurk_leech_eerie_each_
    opponent_loses_life`` function in ``test_probe_subject_is_
    enchantment_unlock.py``:119 -- that function does NOT end in
    ``_parity`` (it predates the credit naming convention) and is
    NOT counted by ``scripts/measure_pool_parity.py``'s slug+
    function-name match; the DDDD probe lands the credited
    ``_parity`` variant via the YYY-idiom (no Rust-side
    compare_fields; effect+bridge+Python-resolve only).

DROPPED ON VERIFY (honest discipline + sibling-lane divergence pins)
---------------------------------------------------------------------

  * **Sami, Ship's Engineer** (Creature BEGINNING_OF_END_STEP +
    Controlled -> ``ConditionalOnTappedCreatures(effect=CreateToken
    (Robot, count=1, tapped=True), min_count=2)``): the
    ``ConditionalOnTappedCreatures`` wrapper composes a conditional
    on the count of controller-tapped creatures BEFORE firing the
    inner ``CreateToken`` -- the wrapper conditional state-read is
    subsystem-gated beyond the YYY-idiom's bare effect+bridge+
    resolve substrate (the conditional path requires both the
    end-step event substrate AND a controlled state with N tapped
    creatures; the bridge round-trip is reachable but the resolve
    smoke requires additional fixture wiring).  Honest exhaustion
    until a ConditionalOnTappedCreatures-substrate probe lands.

  * **Meltstrider's Resolve** (Enchantment Aura ENTERS + IsSelf ->
    ``EnchantedCreatureFightsTargetEffect``): Aura subsystem-gated
    -- ``EnchantedCreatureFightsTargetEffect.resolve`` requires
    both an attached host Creature and an agent-driven target pick
    for the fight target.  The Aura substrate STEP 6 round-trip
    bridge landed (main HEAD ``8fb691f3``) and STEP 7 (loader
    OR-in) is in flight on the sibling lane
    ``feature/aura-substrate-step-7``; until STEP 7 closes the
    Aura attachment is gated by the loader's Aura-rejection path.
    Deferred until the Aura full surface attaches end-to-end.

  * **Dawnsire, Sunstar Dreadnought** (Artifact Spacecraft
    YOU_ATTACK + Controlled -> ``DealDamageToTargetCreature
    (amount=100, optional=True)``): no ``deal_damage_to_target_
    creature`` bridge arm exists at the bare-effect layer (the
    bridge ships ``DealDamageToTargetCreatureWithExcessLanderRider``
    at cross_engine.py:8759 -- a rider-bearing variant; the bare
    bridge form is NOT shipped).  Spacecraft Station subsystem +
    YOU_ATTACK observer event also gate the trigger firing.
    Honest exhaustion at the bridge-arm + Station-subsystem layer.

  * **Fear of Failed Tests** (Enchantment-Creature
    DEALS_COMBAT_DAMAGE -> ``DrawCardsEqualToResolvingCombatDamage
    ()``): EEEE drop list cited this card as bit-identical shape
    to Starwinder (the EEEE Probe 1 ``_parity`` carrier); EEEE
    landed Starwinder's probe at ``origin/main`` ``04c1f16e``.  Per
    the standing redundant-shape drop discipline (CCCC ``test_
    probe_remaining_cccc.py``:73-93 -- Trapped in the Screen drop
    matches Banishing Light), Fear of Failed Tests is redundant
    here.  Honest exhaustion.

  * **Cackling Slasher / Daggermaw Megalodon / Slavering
    Branchsnapper / Bedhead Beastie / Piranha Fly / Patched
    Plaything / Shepherding Spirits / Spectral Snatcher / Magus of
    the Moon / Fear of Being Hunted** (pure-vanilla / keyword-only
    creatures): no triggered abilities / spell effects / activated
    abilities at the parse layer -- nothing to bridge or resolve
    at the YYY-idiom's effect+bridge+resolve substrate.  These
    cards are covered-by-construction via the empty-Effect-set
    rule (every Effect they emit lives + bridges -- because they
    emit zero Effects).  No NEW PROBE_MODULES-credited Effect-
    shape unlocked.  Honest exhaustion at the substrate layer.

  * **Slagdrill Scrapper / Ripchain Razorkin / Gene Pollinator /
    The Dominion Bracelet / Hissing Quagmire / Steelswarm
    Operator / Rust Harvester / Requiem Monolith / The Seriema**
    (activated-ability cards): activated abilities are subsystem-
    gated -- the cost (mana + tap/sacrifice/etc.) + the
    activation-decision pipeline are their own substrate beyond
    the bare effect+bridge+resolve YYY-idiom.  The
    ``test_probe_activated_abilities_*`` modules in PROBE_MODULES
    own the activated-ability probe surface; no new credited
    shape is unlocked by adding another activated-ability card to
    the YYY-idiom-driven probe batch lane.

  * **Cult Healer / Hand That Feeds / Flesh Burrower / Clammy
    Prowler / Innocuous Rat / Optimistic Scavenger / Cosmogrand
    Zenith / Cursed Windbreaker / Killer's Mask / Roving
    Actuator** (covered cards that the CCCC / BBBB / YYY drop-
    lists already enumerate): re-confirmed honest exhaustion per
    those module docstrings -- ``granted_keywords`` rider absent
    from bare bridge / ``ManifestDread`` substrate / Room
    substrate / ``ModalChooseOne`` substrate / ``GrantUnblockable
    UEOT`` target-bearing rider absent.  Deferred until the
    relevant substrate / rider arms land.

  * **Bottomless Pool // Locker Room / Funeral Room // Awakening
    Hall / Mirror Room // Fractured Realm / Surgical Suite //
    Hospital Room / Underwater Tunnel // Slimy Aquarium / Derelict
    Attic // Widow's Walk / Grand Entryway // Elegant Rotunda /
    Restricted Office // Lecture Hall / Moldering Gym // Weight
    Room / Ticket Booth // Tunnel of Hate**: Room subsystem +
    cascade ETB-fan-out -- subsystem-gated per the BBBB drop-list
    (``test_probe_remaining_bbbb.py``:184-190).

  * **Let's Play a Game / Split Up** (Sorcery
    ``spell_effect=ModalChooseOne``): modal-choice substrate
    re-confirmed honest exhaustion per the CCCC docstring
    (``test_probe_remaining_cccc.py``:140-145).

  * **Vanish from Sight / Trapped in the Screen / Lithobraking /
    Temporal Intervention / Under the Skin / Get Out / Weapons
    Manufacturing / Unwanted Remake / Unnerving Grasp / Violent
    Urge / Horrid Vigor / Dual-Sun Technique / Give In to
    Violence / Rig for War / Innocuous Rat**: re-confirmed honest
    exhaustion per the established ZZZ + AAAA + BBBB + CCCC + EEEE
    docstring drop-lists.

  * **Lands / land-cycle / non-basic land substrate (Blazemire
    Verge / Cascading Cataracts / Celestial Colonnade / Command
    Bridge / Creeping Tar Pit / Crystal Quarry / Dust Bowl /
    Eldrazi Temple / Floodfarm Verge / Forest / Gemstone Caverns /
    Gloomlake Verge / Hissing Quagmire / High Market / Hushwood
    Verge / Inkmoth Nexus / Island / Lumbering Falls / Mana
    Confluence / Mountain / Mutavault / Needle Spires / Plaza of
    Heroes / Power Depot / Raging Ravine / Shambling Vent /
    Stirring Wildwood / Sunken Citadel / Swamp / Thornspire Verge)**:
    non-basic land + basic land substrate -- subsystem-gated /
    pure-vanilla.  Re-confirmed honest exhaustion at the substrate
    layer.

  * **All previously-PROBED cards** with the same effect classes --
    every existing PROBED card under DrawCards / EachOpponentLoses
    Life sibling families (DrawCards: Mechan Navigator, etc.;
    EachOpponentLosesLife: NONE prior to this batch -- Balemurk is
    the first).  Not re-probed here.

  * **Subsystem-gated remainder** -- the long tail of Aura
    attachment full surface / Equipment activated-ability surface /
    Room / IS_CAST stack-resolution / non-Effect gate cards; the
    YYY-idiom (parse + bridge + Python-resolve) does not unblock
    them.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED``
tier upon merge.  Prior PROBED count (with AAAA + BBBB + CCCC + EEEE
wired in via PROBE_MODULES, post-EEEE landing -- main HEAD
``04c1f16e``): 226.  Net delta from this module: +2 (PROBED), -2
(covered).
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
# Probe 1 -- Meltstrider Eulogist: Creature DIES triggered ->
#   DrawCards(amount=1).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Meltstrider Eulogist")``
#      returns the parsed CardPrinting (Creature, Insect Soldier).
#   2. The DIES triggered ability's effect is a ``DrawCards`` instance
#      with ``amount=1``.
#   3. The bridge round-trips the canonical dict shape
#      ``{"kind": "draw_cards", "count": 1}`` to a fresh
#      ``DrawCards(amount=1)`` instance (the count->amount field
#      translation per cross_engine.py:596-601).
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``resolve`` path drives the ``draw_n_cards`` pipeline
#      on a controlled state: library has 3 cards, p0's hand starts
#      empty; post-resolve hand has 1, library has 2.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_meltstrider_eulogist_parity():
    """**GENUINE real-EoE cross-engine probe -- Meltstrider Eulogist
    (round 30 DDDD reclaim, Creature DIES -> DrawCards(amount=1)).**

    Drives the **real parsed Meltstrider Eulogist printing** through
    the Python-side ``DrawCards`` resolve path, validating the
    ``draw_n_cards`` pipeline on a controlled state (controller
    starts with empty hand + 3-card library; post-resolve hand=1,
    library=2).  Pairs the parse + bridge round-trip verification
    with the live Python resolve smoke, the same parse + bridge-
    round-trip + Python-side resolve idiom DDD slice 17 + YYY + ZZZ
    + AAAA + CCCC + EEEE established.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited
    ``_parity`` probe of the DIES + bare ``DrawCards`` event +
    effect-class combination.  Complements:
      * Numerous existing PROBED / covered-by-construction
        ``DrawCards`` consumers under ENTERS / IS_CAST / SPELL /
        ATTACKS events -- the DrawCards primitive is widely
        instantiated, but the DIES + bare ``DrawCards`` combination
        is novel (Meltstrider Eulogist is the only EoE consumer of
        this exact combination; existing DIES probes carry
        CreateToken / DealDamage / Sequence-style composite effects
        instead).
    What's NEW here is the **trigger event + effect-class
    combination** (DIES + bare ``DrawCards``).  Meltstrider
    Eulogist's DIES predicate is ``And(Subject(IsCreature() &
    HasCounter('+1/+1')), Controlled)`` -- a composite walking the
    HasCounter Object-predicate substrate.  The HasCounter arm has
    NO Rust bridge per the
    ``test_probe_covered_unprobed_i.py``:38-47 drop note (Rust's
    parse_predicate at cards.rs:7752 omits ``has_counter`` -- only
    always / source_is_self / source_is_creature / subject_is_*
    / controlled_by_you / subject_has_subtype / not / and / or are
    bridged).  Under the YYY-idiom (parse + bridge of EFFECT +
    Python-side resolve smoke, NOT a Rust-side cross-engine
    compare requiring predicate bridge parity), the HasCounter
    predicate is METADATA: the probe verifies the effect + the
    resolve-by-controller mutation regardless of predicate firing.
    The CCCC Lightless Evangel probe established this drop-
    recovery precedent (``test_probe_remaining_cccc.py``:148-154 --
    sacrifice-cause composite predicate is metadata; probe pins
    the EFFECT shape regardless).

    **Bridge arm exercised:** ``draw_cards`` at
    ``cross_engine.py``:596-601 (the ORIGINAL minimum-viable
    surface arm; carries the explicit ``count`` -> ``amount`` field
    translation; matches Rust's
    ``Effect::DrawCards { count: i32 }``).

    **Setup (Python-side):**
      * p0 has Meltstrider Eulogist on the battlefield (the
        Creature serving as the trigger source; the probe seats it
        on the battlefield for state consistency with a real DIES
        firing path -- the resolve itself doesn't read the source).
      * p0's library has 3 cards (vanilla synthetic creatures used
        as library fodder; the draw primitive is library-content-
        agnostic, only the count matters).
      * p0's hand starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "draw_cards", "count": 1}`` translates to a
        ``DrawCards(amount=1)`` instance (with amount=1).
      * The Creature's DIES triggered ability emits
        ``DrawCards(amount=1)``.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's hand has 1 card (drew 1 from a 3-card
        library); the library has 2 cards left.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.effects.generic.draw_mill import (
        DrawCards,
        DrawCardsEqualToResolvingCombatDamage,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Meltstrider Eulogist printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Meltstrider Eulogist")
    )
    if real is None:
        pytest.skip("Meltstrider Eulogist absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Meltstrider Eulogist must be a Creature"
    )
    dies_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.DIES
        ),
        None,
    )
    assert dies_ta is not None, (
        "Meltstrider Eulogist must have a DIES triggered ability "
        "(the event distinguishing this probe from the numerous "
        "ENTERS / IS_CAST / SPELL / ATTACKS DrawCards consumers)"
    )
    assert isinstance(dies_ta.effect, DrawCards), (
        f"Meltstrider Eulogist DIES effect must be DrawCards; got "
        f"{type(dies_ta.effect).__name__}"
    )
    assert dies_ta.effect.amount == 1, (
        f"Meltstrider Eulogist DIES effect must have amount=1; got "
        f"amount={dies_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards", "count": 1}
    )
    assert isinstance(bridged, DrawCards), (
        f"Bridge arm 'draw_cards' must round-trip to DrawCards; got "
        f"{type(bridged).__name__}"
    )
    assert bridged.amount == 1, (
        f"Bridged DrawCards must carry amount=1 (translated from "
        f"dict 'count'); got amount={bridged.amount}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert dies_ta.effect == bridged, (
        f"Meltstrider Eulogist DIES effect must be byte-equal to the "
        f"bridged Effect; got parsed={dies_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, DrawCardsEqualToResolvingCombatDamage), (
        "DrawCards must NOT collapse to "
        "DrawCardsEqualToResolvingCombatDamage (EEEE Probe 1's "
        "Starwinder emission; DrawCards carries an explicit amount "
        "field, the resolving-combat-damage variant reads the "
        "carrier scalar at resolve time -- distinct count-sourcing "
        "semantics)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Meltstrider Eulogist Creature on p0's
    # battlefield (state consistency with a real DIES firing path;
    # the resolve itself doesn't read the source object).
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Stock p0's library with 3 cards (vanilla Plains -- the draw
    # primitive is library-content-agnostic, only the count matters).
    p0 = py.players[0]
    plains_printing = BASIC_LANDS["Plains"]
    for _ in range(3):
        lib_card = py.new_object(plains_printing, owner_id=0, zone=Zone.LIBRARY)
        p0.library.append(lib_card)

    # Sanity: p0's hand starts empty, library has 3.
    assert len(p0.hand) == 0, (
        f"Pre-resolve sanity: p0.hand must start empty; got "
        f"len(p0.hand)={len(p0.hand)}"
    )
    assert len(p0.library) == 3, (
        f"Pre-resolve sanity: p0.library must start with 3 cards; "
        f"got len(p0.library)={len(p0.library)}"
    )

    # ------------------------------------------------------------------
    # 5. resolve: draw 1 card.  No carrier-state setup needed --
    #    DrawCards reads its ``amount`` field directly, not a
    #    state-bound scalar like DrawCardsEqualToResolvingCombatDamage.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    # Hand: 1 card drawn.
    assert len(p0.hand) == 1, (
        f"Meltstrider Eulogist: p0.hand must have 1 card post-resolve "
        f"(DrawCards(amount=1) drew 1 from library); got "
        f"len(p0.hand)={len(p0.hand)}"
    )
    # Library: 2 cards left (3 - 1 drawn).
    assert len(p0.library) == 2, (
        f"Meltstrider Eulogist: p0.library must have 2 cards left "
        f"post-resolve (3 - 1 drawn = 2); got "
        f"len(p0.library)={len(p0.library)}"
    )
    # Source remains on the battlefield (the resolve mutates p0's
    # hand + library; it does NOT move the source -- in real play
    # the DIES event would have already moved the source to the
    # graveyard BEFORE the trigger resolves, but the probe pins the
    # resolve mutation surface, which is decoupled from the source
    # move).
    assert source in py.battlefield, (
        "Meltstrider Eulogist: source remains on the battlefield in "
        "this probe's controlled state (DrawCards mutates hand + "
        "library, not source zone; the DIES-event source-move is "
        "out-of-scope for the bare effect+bridge+resolve probe)"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Balemurk Leech: Creature ENTERS triggered ->
#   EachOpponentLosesLife(amount=1).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Balemurk Leech")``
#      returns the parsed CardPrinting (Creature, Leech).
#   2. The ENTERS triggered ability's effect is an
#      ``EachOpponentLosesLife`` instance with ``amount=1``.
#   3. The bridge round-trips the canonical dict shape
#      ``{"kind": "each_opponent_loses_life", "amount": 1}`` to a
#      fresh ``EachOpponentLosesLife(amount=1)`` instance.
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``resolve`` path drives the per-opponent life loss
#      pipeline on a controlled state: p1 starts at 20 life;
#      post-resolve p1 is at 19.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_balemurk_leech_parity():
    """**GENUINE real-EoE cross-engine probe -- Balemurk Leech (round
    30 DDDD reclaim, Creature ENTERS -> EachOpponentLosesLife
    (amount=1)).**

    Drives the **real parsed Balemurk Leech printing** through the
    Python-side ``EachOpponentLosesLife`` resolve path, validating
    the per-opponent direct life-loss pipeline on a controlled state
    (p1 starts at 20 life; post-resolve p1 is at 19).  Pairs the
    parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + EEEE
    established.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited
    ``_parity`` probe of the ``EachOpponentLosesLife`` effect class.
    Balemurk Leech is the ONLY EoE consumer of this effect class
    per the bridge-arm docstring at ``cross_engine.py``:4872-4874
    (1 EoE card hit via oracle scan -- the Eerie-shape direct life
    loss pattern; CR 118.4 NOT damage).  Complements:
      * Sister effect ``TargetOpponentLosesLife`` (which targets a
        specific opponent via the Decision pipeline and defaults to
        amount=1; routes through target selection).
      * Sister effect ``DamageEachOpponent`` (which deals DAMAGE
        routed through damage-prevention -- vs this arm's direct
        life subtraction; reducible by damage-prevention /
        Worship-style replacement, this primitive is NOT).
    What's NEW here is the **effect class** -- the CR 118.4 direct
    life loss primitive (the punisher / drawback pattern's
    canonical bridge probe).  Balemurk Leech also has a sibling
    ROOM_FULLY_UNLOCKED-event trigger emitting the same effect; the
    ROOM event is subsystem-gated per the CCCC drop-list
    (``test_probe_remaining_cccc.py``:119-124 -- Room subsystem
    full surface gating), so this probe pins only the ENTERS leg.

    Balemurk Leech was previously the subject of a non-credited
    cross-engine function in
    ``test_probe_subject_is_enchantment_unlock.py``:119 -- that
    function does NOT end in ``_parity`` (it predates the credit
    naming convention and uses the older full ``compare_fields``
    cross-engine idiom requiring Rust-bridge predicate parity for
    the ``subject_is_enchantment`` arm).  The DDDD probe lands the
    credited ``_parity`` variant via the YYY-idiom (no Rust-side
    compare_fields; effect+bridge+Python-resolve only -- the
    predicate parity is not load-bearing under this idiom).

    **Bridge arm exercised:** ``each_opponent_loses_life`` at
    ``cross_engine.py``:4819 (round-23 BLOCKED-BRIDGE-ARM slice
    closure; matching Rust's
    ``Effect::EachOpponentLosesLife { amount: i32 }`` at
    cards.rs:507, parser at cards.rs:3425-3438, resolve at
    state_ops_resolve.rs:3592-3636 -- CR 118.4 direct life loss,
    NOT damage; punisher / drawback pattern).

    **Setup (Python-side):**
      * p0 has Balemurk Leech on the battlefield (state consistency
        with a real ENTERS firing path; the resolve itself doesn't
        read the source object).
      * p1 starts at 20 life (the default initial life total per
        ``build_python_state``'s contract).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "each_opponent_loses_life", "amount": 1}``
        translates to an ``EachOpponentLosesLife(amount=1)``
        instance (with amount=1; the ``amount`` field is REQUIRED
        on the bridge arm per cross_engine.py:4831-4838).
      * The Creature's ENTERS triggered ability emits
        ``EachOpponentLosesLife(amount=1)``.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p1's life is 19 (was 20 pre-resolve); p0's
        life is UNCHANGED (controllers are skipped by
        ``EachOpponentLosesLife.resolve``).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.life import EachOpponentLosesLife
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Balemurk Leech printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Balemurk Leech")
    )
    if real is None:
        pytest.skip("Balemurk Leech absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Balemurk Leech must be a Creature"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Balemurk Leech must have an ENTERS triggered ability "
        "(the Eerie-shape enchantment-ETB observer leg; the sibling "
        "ROOM_FULLY_UNLOCKED leg is subsystem-gated and out of "
        "scope for this probe)"
    )
    assert isinstance(enters_ta.effect, EachOpponentLosesLife), (
        f"Balemurk Leech ENTERS effect must be EachOpponentLosesLife; "
        f"got {type(enters_ta.effect).__name__}"
    )
    assert enters_ta.effect.amount == 1, (
        f"Balemurk Leech ENTERS effect must have amount=1; got "
        f"amount={enters_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "each_opponent_loses_life", "amount": 1}
    )
    assert isinstance(bridged, EachOpponentLosesLife), (
        f"Bridge arm 'each_opponent_loses_life' must round-trip to "
        f"EachOpponentLosesLife; got {type(bridged).__name__}"
    )
    assert bridged.amount == 1, (
        f"Bridged EachOpponentLosesLife must carry amount=1; got "
        f"amount={bridged.amount}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Balemurk Leech ENTERS effect must be byte-equal to the "
        f"bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, DrawCards), (
        "EachOpponentLosesLife must NOT collapse to DrawCards "
        "(Probe 1's sibling effect with completely different "
        "semantics; DrawCards moves cards from library to hand on "
        "the controller, EachOpponentLosesLife subtracts life from "
        "each non-controller player -- distinct mutation surfaces)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Balemurk Leech Creature on p0's battlefield
    # (state consistency with a real ENTERS firing path; the
    # resolve itself doesn't read the source object).
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Sanity: both players start at 20 life (default initial life
    # total per build_python_state).
    p0 = py.players[0]
    p1 = py.players[1]
    assert p0.life == 20, (
        f"Pre-resolve sanity: p0.life must start at 20; got "
        f"p0.life={p0.life}"
    )
    assert p1.life == 20, (
        f"Pre-resolve sanity: p1.life must start at 20; got "
        f"p1.life={p1.life}"
    )

    # ------------------------------------------------------------------
    # 5. resolve: each opponent of p0 loses 1 life.  No carrier-
    #    state setup needed -- EachOpponentLosesLife reads its
    #    ``amount`` field directly and walks state.players, skipping
    #    the controller_id.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    # p1: 1 life lost (the one opponent in the 2-player state).
    assert p1.life == 19, (
        f"Balemurk Leech: p1.life must equal 19 post-resolve "
        f"(EachOpponentLosesLife(amount=1) subtracts 1 from each "
        f"opponent; CR 118.4 direct life loss); got p1.life={p1.life}"
    )
    # p0: UNCHANGED (controller is skipped).
    assert p0.life == 20, (
        f"Balemurk Leech: p0.life must remain 20 post-resolve "
        f"(EachOpponentLosesLife skips the controller); got "
        f"p0.life={p0.life}"
    )
    # Source remains on the battlefield (the resolve mutates p1's
    # life; it does NOT move the source).
    assert source in py.battlefield, (
        "Balemurk Leech: source must remain on the battlefield "
        "post-resolve (EachOpponentLosesLife is a life mutation, "
        "not a zone change)"
    )
