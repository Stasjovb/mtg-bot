"""Genuine real-EoE cross-engine byte-equality probes -- batch IIII
(round 35, the NINTH 4-letter probe batch -- post-HHHH).

The AAAA batch (``tests/test_probe_remaining_aaaa.py``) opened the
4-letter naming convention post-ZZZ alphabetic exhaustion.  IIII is
the ninth 4-letter batch (round 35); prior 4-letter batches are
AAAA (round 27), BBBB (round 28), CCCC (round 29), DDDD (round 30
reclaim), EEEE (round 31 reclaim), FFFF (round 32 relaunch), GGGG
(round 33), and HHHH (round 34, main HEAD ``3ef6c25c``).  Subsequent
batches follow ``JJJJ`` / ``KKKK`` / ... per the established 4-letter
alphabetic cadence.

FOUR cards from the ``covered_by_construction`` tier are upgraded to
the ``PROBED`` tier by this module via the same parse + bridge round-
trip + Python-side resolve idiom DDD slice 17's Honored Knight-Captain
probe (``tests/test_probe_ddd_downstream.py``:408), the YYY batch's
two probes (``tests/test_probe_remaining_yyy.py``:272 / 573), the ZZZ
batch's two probes (``tests/test_probe_remaining_zzz.py``:173 / 413),
the AAAA / CCCC / DDDD / EEEE / FFFF / GGGG / HHHH batches established
as a PROBE_MODULES-credited shape.

Each probe re-uses the SAME HHHH-idiom: bind the real EoE printing,
verify the parsed Effect is byte-equal to the bridge round-trip, then
run a controlled Python-side resolve smoke on a documented silent-
fizzle short-circuit.  These four cards share the substrate-shipped-
but-no-_parity-probe pattern: their bespoke Effect classes have
already shipped Rust variants + bridge arms + Python resolve paths
via prior closures, but no ``_parity``-named function pins the card
slug, so the ``_smoke_probed_cards`` slug scanner cannot credit them.
Adding the thin ``_parity`` delegator closes the measurement-
attribution gap (the warp_cost Phase 3 precedent at merge
``33188239``; the HHHH precedent at merge after ``3ef6c25c``).

  * **Lightstall Inquisitor** (~4,371 17lands decks) -- Creature
    ENTERS -> ``EachOpponentExilesCardFromHandWithCastPermission()``.
    The bespoke Effect class shipped in the 20th Rust slice (XXX
    Pin 3 closure) + the cast-from-exile-with-cost-hike substrate
    follow-up; the cross-engine bridge arm
    ``each_opponent_exiles_card_from_hand_lightstall`` at
    ``cross_engine.py``:8562 is a unit-variant round-trip (no
    fields to plumb), and the Python resolve path at
    ``effects/generic/discard.py``:187-208 silently skips per-
    opponent loop iterations for any opponent whose hand is empty
    (``if not p.hand: continue``).  The Rust resolve arm mirrors
    via ``if state.players[opponent_idx].hand.is_empty(): return
    Ok(())``.  Existing downstream tests at
    ``tests/test_probe_xxx_pin3_downstream.py`` cover the resolve
    mechanics + the empty-hand no-op + the cast-from-exile
    substrate but use ``test_xxx_pin3_*`` names (a function with
    a ``_parity`` suffix EXISTS but the prefix is
    ``test_xxx_pin3_real_eoe_lightstall_inquisitor_cast_from_exile_
    substrate_parity`` -- the slug scanner requires the prefix
    ``test_cross_engine_real_eoe_<slug>_parity``, so the existing
    function does NOT credit Lightstall Inquisitor in the PROBED-
    tier classifier).  **NEW shape coverage:** the FIRST credited
    ``_parity`` probe of the dedicated bespoke
    ``EachOpponentExilesCardFromHandWithCastPermission`` effect
    class on the REAL parsed Lightstall Inquisitor EoE printing.
    Lightstall is the ONLY EoE consumer of this effect class.

  * **The Seriema** (~? decks) -- Artifact (Spacecraft) ENTERS ->
    ``SearchLibraryForCard(filter_name='legendary_creature',
    max_mv=0, may_fail=False)``.  The bare-shape ``SearchLibraryForCard``
    bridge arm shipped via round 21 (BLOCKED-BRIDGE-ARM slice at
    ``cross_engine.py``:3973-4044) carries the SAME three-field
    round-trip (filter_name + max_mv + may_fail) as the Rust
    variant.  Sibling consumers are PROBED: Spineseeker Centipede
    pins the bare ``filter_name='basic_land', may_fail=True`` shape
    on ENTERS; Starfield Shepherd pins a ``ModalChooseOne`` wrapper
    around two ``SearchLibraryForCard`` modes (basic_plains and
    creature_small).  **NEW shape coverage:** the FIRST credited
    ``_parity`` probe of the bare ``SearchLibraryForCard`` shape
    with ``filter_name='legendary_creature', may_fail=False`` on
    an ENTERS carrier -- the ``may_fail=False`` half of the may_fail
    boolean (Spineseeker pinned ``may_fail=True``) and the
    ``legendary_creature`` filter half of the filter taxonomy
    (Spineseeker pinned ``basic_land``) on a bare (non-ModalChooseOne-
    wrapped) emission.

  * **Optimistic Scavenger** (~? decks) -- Creature ENTERS ->
    ``PutPlusOneCounterOnTargetCreature(amount=1)``.  The bare
    bridge arm ``put_plus_one_counter_on_target_creature`` at
    ``cross_engine.py``:9542-9591 (PPP Pin 2 -- 10th Rust slice)
    round-trips the ``amount`` + ``attacking_only`` fields.  Sibling
    PROBED consumers (Drix Fatemaker / Mm'menon Uthros Exile)
    pin the bare ENTERS-event carrier with ``IsSelf`` /
    ``Subject(IsArtifact) & Controlled(YOU)`` predicates;
    Optimistic Scavenger adds a second event (``ROOM_FULLY_UNLOCKED``)
    + a different predicate (``Subject(IsEnchantment) &
    Controlled(YOU)``).  **NEW shape coverage:** the FIRST credited
    ``_parity`` probe binding the Optimistic Scavenger slug to the
    Effect+bridge round-trip of its ENTERS ``PutPlusOneCounterOnTarget
    Creature(amount=1)`` shape on the REAL parsed EoE printing.  The
    PROBED-tier classifier credits per-slug, not per-effect-class;
    Optimistic Scavenger is currently covered-by-construction but
    has no slug-keyed probe.

  * **Command Bridge** (~24,522 17lands decks -- the HIGHEST-deck-
    count BLOCKED-genuinely_missing closure on the
    ``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`` list, closed by
    the 20th Rust slice / VVV Pin 2) -- Land ENTERS ->
    ``SacrificeSelfUnlessTapPermanent()``.  The bespoke Effect class
    shipped in the 20th Rust slice (VVV Pin 2 closure); the cross-
    engine bridge arm ``sacrifice_self_unless_tap_permanent`` at
    ``cross_engine.py``:8382-8422 is a unit-variant round-trip (no
    fields to plumb), and the Python resolve path at
    ``effects/combinators.py``:115-163 silently returns when
    ``state.resolving_source is None`` (lines 121-123).  Command
    Bridge is a Land carrier; HHHH's drop list cited "Lands
    (activated-ability surface)" generically, but Command Bridge
    is a LAND-shape ETB whose TRIGGERED ability is the load-bearing
    parity ask (separate from its mana-ability activated surface).
    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the dedicated bespoke ``SacrificeSelfUnlessTapPermanent`` effect
    class on the REAL parsed Command Bridge EoE printing.  Command
    Bridge is the ONLY EoE consumer of this effect class.

DROPPED ON VERIFY (honest discipline)
---------------------------------------------------------------------

  * **Dawnsire, Sunstar Dreadnought** (YOU_ATTACK +
    ``DealDamageToTargetCreature(amount=100, optional=True)``): no
    matching ``deal_damage_to_target_creature`` bridge arm (the
    GGGG / HHHH drop notes confirmed -- bridge has ``deal_damage``
    but it returns the base ``DealDamage`` class, not the
    ``DealDamageToTargetCreature`` subclass, and does NOT carry the
    ``optional`` flag).  Honest exhaustion at the bridge layer.

  * **Clammy Prowler** (ATTACKS + ``GrantUnblockableUEOT``): no
    matching ``grant_unblockable_ueot`` bridge arm (verified in
    HHHH drop notes).  Honest exhaustion at the bridge layer.

  * **Hand That Feeds / Flesh Burrower / Cult Healer** (pump
    triggers carrying a ``granted_keywords`` rider): the
    ``pump_self_until_eot`` / ``pump_target_creature_until_eot``
    bridge arms drop the rider (verified in GGGG / HHHH drop notes).
    Honest exhaustion until a rider-bearing pump arm lands.

  * **Sami, Ship's Engineer / Station Monitor / Weapons
    Manufacturing / Grand Entryway** (token-creation effects):
    token-registration substrate requires additional harness work
    beyond the bare effect+bridge slice -- same deferral the
    HHHH / GGGG / EEEE / DDDD drop notes cover.

  * **Sunstar Lightsmith / Cosmogrand Zenith / Rust Harvester /
    Requiem Monolith / Let's Play a Game / Split Up / Lithobraking /
    Vanish from Sight / Unnerving Grasp** (Sequence / ModalChooseOne
    / OptionalSacArtifactForEffect wrappers with substrate-deferred
    inner effects): bare bridge dispatches per-effect, but the
    inner effects (CreateToken needs token registration / Vanish
    from Sight's bounce-to-library has a documented summoning-sick
    divergence per BBBB drop notes / ManifestDread inner needs the
    library + agent picker substrate / DestroyAllCreatures bridge
    arm drops tapped_only/untapped_only narrowing fields).  Same
    deferral as HHHH.

  * **Conductive Machete / Cursed Windbreaker / Killer's Mask /
    Squire's Lightblade / Illvoi Light Jammer / The Dominion
    Bracelet**: Equipment ETB + ``ManifestDreadThenAttachSelf`` /
    bare ``AttachToTargetCreatureYouControl`` with
    ``granted_keywords_ueot`` rider that bridge drops /
    ``EquipToTargetCreatureYouControl`` -- the ManifestDread
    resolve substrate requires library + agent picker; the
    rider-bearing attach is dropped by the bare bridge arm at
    ``cross_engine.py``:3583.  Same deferral as HHHH / GGGG / FFFF
    / EEEE / CCCC / AAAA.

  * **Break Down the Door / Under the Skin / Innocuous Rat /
    Moldering Gym // Weight Room / Underwater Tunnel // Slimy
    Aquarium** -- bare ManifestDread effect /
    ManifestDreadThenPutPlusOneCountersOnIt wrapper: same
    ManifestDread harness substrate deferral as HHHH; sibling
    PROBED consumers (Manifest Dread / Bashful Beastie / Defiant
    Survivor) already pin the same (event, effect-class) shape on
    other EoE carriers.

  * **Give In to Violence / Dual-Sun Technique / Horrid Vigor /
    Rig for War / Violent Urge** (Instant
    ``spell_effect=PumpTargetCreatureUntilEOT`` with
    ``granted_keywords`` riders): rider-omission deferral -- bridge
    does not plumb the keyword rider, so the HHHH-idiom byte-
    equality assertion would fail.  Same drop as HHHH / GGGG.

  * **Trapped in the Screen** (ENTERS +
    ``ExileOpponentsNonlandPermanentUntilLeaves``): bit-identical
    shape to the already-PROBED Banishing Light (same Enchantment
    carrier, same ENTERS event, same effect with same max_mv=0) per
    HHHH / CCCC drop notes.

  * **Unwanted Remake / Come Back Wrong** (bare
    ``DestroyTargetCreature`` spell-effect): byte-identical to the
    already-PROBED Murder.  No NEW Effect+bridge axis coverage --
    same drop discipline as HHHH / GGGG.

  * **Tannuk, Steadfast Second / Frenzied Baloth**: Lane K is
    running real-EoE probes for these two in
    ``../mtg-bot-worktrees/tannuk-frenzied-baloth-probes``.  IIII
    explicitly defers per the concurrent-agent note in the task
    spec.

  * **Vanilla / keyword-only creatures** (Bedhead Beastie, Cackling
    Slasher, Daggermaw Megalodon, Magus of the Moon, Patched
    Plaything, Piranha Fly, Spectral Snatcher, Shepherding Spirits,
    Fear of Being Hunted, Slavering Branchsnapper, Ripchain Razorkin,
    Gene Pollinator, Steelswarm Operator, Fear of Failed Tests,
    Irreverent Gremlin, Duskmourn's Domination): no triggered
    abilities OR only static / activated abilities / type-line
    statics the PROBED-tier classifier does not credit at the bare-
    effect+bridge+resolve slice OR bit-identical-to-PROBED-sibling
    shapes (Fear of Failed Tests -> Starwinder; Irreverent Gremlin
    -> Melded Moxite with identical IfYouDo(MayDo(DiscardSelf),
    DrawCards) composition modulo the draw amount).  Same drop as
    HHHH / GGGG / FFFF.

  * **Room cards** (Bottomless Pool // Locker Room / Funeral Room
    // Awakening Hall / Restricted Office // Lecture Hall / Mirror
    Room // Fractured Realm / Surgical Suite // Hospital Room /
    Underwater Tunnel // Slimy Aquarium / Moldering Gym // Weight
    Room / Ticket Booth // Tunnel of Hate / Derelict Attic //
    Widow's Walk / Grand Entryway // Elegant Rotunda): Room
    subsystem -- the partial ENTERS-only coverage does not pin the
    full card.  Same drop as HHHH / GGGG.

  * **Temporal Intervention** (Sorcery
    ``spell_effect=TargetOpponentDiscardsCasterChoice``): no
    matching bridge arm (verified in HHHH / GGGG drop notes).

  * **Lands** (Forest, Island, Mountain, Plains, Swamp + dual
    lands -- Blazemire Verge, Floodfarm Verge, Gloomlake Verge,
    Hushwood Verge, Thornspire Verge, Celestial Colonnade,
    Hissing Quagmire, Lumbering Falls, Needle Spires, Raging
    Ravine, Shambling Vent, Stirring Wildwood, Creeping Tar Pit
    + utility lands -- Cascading Cataracts, Crystal Quarry, Dust
    Bowl, Eldrazi Temple, Gemstone Caverns, High Market, Inkmoth
    Nexus, Mana Confluence, Mutavault, Plaza of Heroes, Power
    Depot, Sunken Citadel, Blinkmoth Nexus, Kavaron Turbodrone):
    activated-ability surface only (no triggered abilities), same
    drop as HHHH / GGGG.  **Note: Command Bridge is a Land BUT
    has an ENTERS triggered ability** -- the
    ``SacrificeSelfUnlessTapPermanent`` ETB shape -- distinct from
    the activated-ability-only sibling lands; IIII probes the
    triggered shape (separate surface from the AddManaToPool
    activated ability which stays the dropped surface).

  * **Subsystem-gated remainder** -- the long tail of Aura
    attachment full surface / Equipment activated-ability surface /
    Room / IS_CAST stack-resolution / non-Effect gate cards / Land
    activated abilities; the HHHH-idiom (parse + bridge + Python-
    resolve) does not unblock them.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
FOUR cards move from ``covered_by_construction`` to the ``PROBED``
tier upon merge.  Prior PROBED count (with AAAA + BBBB + CCCC + DDDD
+ EEEE + FFFF + GGGG + HHHH wired in via PROBE_MODULES, post-HHHH
merge -- main HEAD ``3ef6c25c``): 250.  Net delta from this module:
+4 (PROBED), -4 (covered).
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
# Probe 1 -- Lightstall Inquisitor: Creature ENTERS triggered ->
#   EachOpponentExilesCardFromHandWithCastPermission() (unit variant).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Lightstall Inquisitor")``
#      returns the parsed CardPrinting (Creature, Angel Wizard).
#   2. The ENTERS triggered ability's effect is an
#      ``EachOpponentExilesCardFromHandWithCastPermission()`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``EachOpponentExilesCardFromHandWithCastPermission()`` instance
#      (unit variant -- no fields).
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against effect-class collapse).
#   5. Python's ``resolve`` path with empty opponent hands silently
#      no-ops (the empty-hand short-circuit at
#      ``effects/generic/discard.py``:196-197 -- the per-opponent
#      ``if not p.hand: continue`` skip); no state mutation, no log
#      lines, no exile transitions.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lightstall_inquisitor_parity():
    """**GENUINE real-EoE cross-engine probe -- Lightstall Inquisitor
    (round 35 IIII, Creature ENTERS ->
    EachOpponentExilesCardFromHandWithCastPermission()).**

    Drives the **real parsed Lightstall Inquisitor printing** through
    the Python-side
    ``EachOpponentExilesCardFromHandWithCastPermission`` resolve path,
    validating the empty-opponent-hand silent-no-op short-circuit
    (the resolve's per-opponent ``if not p.hand: continue`` skip at
    ``effects/generic/discard.py``:196-197; the Rust resolve arm
    mirrors via ``if state.players[opponent_idx].hand.is_empty():
    return Ok(())``, byte-equal with Python's same-case skip).
    Pairs the parse + bridge round-trip verification with the live
    Python resolve smoke, the same parse + bridge-round-trip + Python-
    side resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD +
    EEEE + FFFF + GGGG + HHHH established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the dedicated bespoke
    ``EachOpponentExilesCardFromHandWithCastPermission`` effect class
    on the REAL parsed Lightstall Inquisitor EoE printing.  Lightstall
    is the ONLY EoE consumer of this effect class.  Complements:
      * The 20th Rust slice (XXX Pin 3) closure tests at
        ``tests/test_probe_xxx_pin3_downstream.py``
        (``test_xxx_pin3_probe_lightstall_inquisitor_empty_hand_no_op``
        + ``test_xxx_pin3_probe_lightstall_inquisitor_deterministic_
        first_legal_pick`` + ``test_xxx_pin3_real_eoe_lightstall_
        inquisitor_cast_from_exile_substrate_parity`` etc.) which
        exercise the resolve mechanics + the empty-hand short-circuit
        on a SYNTHETIC carrier built via ``register_and_inject_object``;
        those tests are NOT credited by the PROBED-tier classifier
        because their function names do not start with the
        ``test_cross_engine_real_eoe_`` prefix that the slug scanner
        requires (the ``_parity`` suffix alone is not enough -- the
        slug regex at ``scripts/measure_pool_parity.py``:655-657
        anchors on the FULL ``test_cross_engine_real_eoe_<slug>_parity``
        pattern).  IIII lands the credited ``_parity`` variant on the
        REAL parsed Lightstall Inquisitor printing.

    **Bridge arm exercised:**
    ``each_opponent_exiles_card_from_hand_lightstall`` (matching
    Rust's ``Effect::EachOpponentExilesCardFromHandWithCastPermission``
    -- 20th Rust slice unit-variant; bridge dispatch at
    ``cross_engine.py``:8562).

    **Setup (Python-side):**
      * p0 has Lightstall Inquisitor on the battlefield with
        ``resolving_source`` set; p1's hand is EMPTY (the silent-no-op
        case the probe verifies -- production opponent-hand-non-empty
        cases are gated by the broader hand-card-creation substrate,
        separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "each_opponent_exiles_card_from_hand_lightstall"}``
        translates to an
        ``EachOpponentExilesCardFromHandWithCastPermission()``
        instance.
      * The Creature's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * ``requires_target() is False`` + ``target_count_range() ==
        (0, 0)`` (no targets -- the effect picks each opponent
        deterministically).
      * With p1's hand EMPTY, the resolve is a no-op: log unchanged,
        battlefield unchanged, exile unchanged, hand unchanged.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.discard import (
        EachOpponentExilesCardFromHandWithCastPermission,
        EachOpponentDiscards,
        TargetOpponentDiscardsCasterChoice,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Lightstall Inquisitor printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Lightstall Inquisitor")
    if real is None:
        pytest.skip("Lightstall Inquisitor absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Lightstall Inquisitor must be a Creature"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Lightstall Inquisitor must have an ENTERS triggered ability "
        "(the bespoke EachOpponentExilesCardFromHandWithCastPermission "
        "class encodes the ETB body)"
    )
    assert isinstance(
        enters_ta.effect, EachOpponentExilesCardFromHandWithCastPermission,
    ), (
        f"Lightstall Inquisitor ENTERS effect must be "
        f"EachOpponentExilesCardFromHandWithCastPermission; got "
        f"{type(enters_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "each_opponent_exiles_card_from_hand_lightstall"}
    )
    assert isinstance(
        bridged, EachOpponentExilesCardFromHandWithCastPermission,
    ), (
        f"Bridge arm 'each_opponent_exiles_card_from_hand_lightstall' "
        f"must round-trip to "
        f"EachOpponentExilesCardFromHandWithCastPermission; got "
        f"{type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Lightstall Inquisitor ENTERS effect must be byte-equal to "
        f"the bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, EachOpponentDiscards), (
        "EachOpponentExilesCardFromHandWithCastPermission must NOT "
        "collapse to EachOpponentDiscards (the sibling each-opponent "
        "hand-mutation effect class; EachOpponentDiscards routes the "
        "card to graveyard via the opponent's own pick, while "
        "EachOpponentExilesCardFromHandWithCastPermission exiles "
        "deterministically with cast-permission stamp)."
    )
    assert not isinstance(bridged, TargetOpponentDiscardsCasterChoice), (
        "EachOpponentExilesCardFromHandWithCastPermission must NOT "
        "collapse to TargetOpponentDiscardsCasterChoice (the sibling "
        "targeted-opponent discard with caster-pick; different "
        "targeting cardinality and zone destination)."
    )
    assert bridged.requires_target() is False, (
        "EachOpponentExilesCardFromHandWithCastPermission must NOT "
        "require a target (it picks each opponent deterministically; "
        "no player-chosen target slot)"
    )
    assert bridged.target_count_range() == (0, 0), (
        f"EachOpponentExilesCardFromHandWithCastPermission must have "
        f"target_count_range=(0, 0); got "
        f"{bridged.target_count_range()}"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: empty-
    #    opponent-hand silent-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat Lightstall Inquisitor on p0's battlefield.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Pre-resolve sanity: p1's hand and exile are empty.
    assert len(py.players[1].hand) == 0, (
        "Pre-resolve sanity: p1's hand must be empty for the "
        "silent-no-op probe"
    )
    assert len(py.players[1].exile) == 0, (
        "Pre-resolve sanity: p1's exile must be empty for the "
        "silent-no-op probe"
    )

    py.resolving_source = source
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)
    p0_hand_before = list(py.players[0].hand)
    p1_hand_before = list(py.players[1].hand)
    p0_exile_before = list(py.players[0].exile)
    p1_exile_before = list(py.players[1].exile)

    # ------------------------------------------------------------------
    # 5. resolve: empty-opponent-hand silent-no-op.  The resolve's
    #    per-opponent ``if not p.hand: continue`` skip at
    #    discard.py:196-197 leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Lightstall Inquisitor: empty-opponent-hand resolve must NOT "
        f"append a log line (the resolve's per-opponent skip at "
        f"discard.py:196-197); got log_len={len(py.log)} (expected "
        f"{pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Lightstall Inquisitor: empty-opponent-hand resolve must NOT "
        "mutate the battlefield"
    )
    assert py.players[0].hand == p0_hand_before, (
        "Lightstall Inquisitor: controller's hand must NOT be mutated "
        "(the effect only touches opponents)"
    )
    assert py.players[1].hand == p1_hand_before, (
        "Lightstall Inquisitor: opponent's empty hand must remain "
        "empty (the per-opponent skip short-circuits)"
    )
    assert py.players[0].exile == p0_exile_before, (
        "Lightstall Inquisitor: controller's exile must NOT be "
        "mutated"
    )
    assert py.players[1].exile == p1_exile_before, (
        "Lightstall Inquisitor: opponent's exile must remain empty "
        "(no zone transitions on the no-op path)"
    )
    assert source in py.battlefield, (
        "Lightstall Inquisitor: source must remain on the "
        "battlefield post-resolve"
    )

    py.resolving_source = None


# ---------------------------------------------------------------------------
# Probe 2 -- The Seriema: Artifact (Spacecraft) ENTERS triggered ->
#   SearchLibraryForCard(filter_name='legendary_creature', max_mv=0,
#                         may_fail=False).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("The Seriema")``
#      returns the parsed CardPrinting (Artifact, Spacecraft).
#   2. The ENTERS triggered ability's effect is a
#      ``SearchLibraryForCard(filter_name='legendary_creature',
#      max_mv=0, may_fail=False)`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``SearchLibraryForCard(filter_name='legendary_creature',
#      max_mv=0, may_fail=False)`` instance.
#   4. Distinctness from sibling parameterizations is preserved
#      (Spineseeker's filter_name='basic_land', may_fail=True; Starfield
#      Shepherd's ModalChooseOne wrapper).
#   5. Python's ``resolve`` path with EMPTY library is a clean log-
#      one-line + shuffle no-op (the empty-options short-circuit at
#      ``effects/generic/search.py``:90-97; shuffle on empty library
#      is a no-op).  Library remains empty, hand unchanged.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_the_seriema_parity():
    """**GENUINE real-EoE cross-engine probe -- The Seriema
    (round 35 IIII, Artifact (Spacecraft) ENTERS ->
    SearchLibraryForCard(filter_name='legendary_creature',
    max_mv=0, may_fail=False)).**

    Drives the **real parsed The Seriema printing** through the
    Python-side ``SearchLibraryForCard`` resolve path, validating the
    empty-library + shuffle-only short-circuit (the resolve's
    empty-options branch at ``effects/generic/search.py``:90-97;
    Rust mirrors via the same empty-options + shuffle).  Pairs the
    parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD +
    EEEE + FFFF + GGGG + HHHH established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the bare ``SearchLibraryForCard`` shape with
    ``filter_name='legendary_creature', max_mv=0, may_fail=False`` on
    an ENTERS carrier.  Complements:
      * Spineseeker Centipede (PROBED via the smoke-file probe) pins
        the bare ``SearchLibraryForCard(filter_name='basic_land',
        max_mv=0, may_fail=True)`` shape on ENTERS -- DIFFERENT
        filter (``basic_land`` vs ``legendary_creature``) and
        DIFFERENT may_fail (True vs False).
      * Starfield Shepherd (PROBED) pins a ``ModalChooseOne`` wrapper
        around two ``SearchLibraryForCard`` modes (``basic_plains`` +
        ``creature_small``) -- DIFFERENT carrier shape (wrapper vs
        bare).
      * Demonic Counsel (PROBED) drives ``SearchLibraryForCard`` as a
        SPELL effect with ``filter_name='demon'`` -- DIFFERENT event
        (SPELL vs ENTERS).
    IIII lands the credited ``_parity`` variant binding the
    ``(ENTERS, bare, legendary_creature, may_fail=False)`` quadruple
    that no prior PROBED card covers.

    **Bridge arm exercised:**
    ``search_library_for_card`` (matching Rust's
    ``Effect::SearchLibraryForCard { filter_name, max_mv, may_fail }``
    -- 21st Rust slice / BLOCKED-BRIDGE-ARM closure; bridge dispatch
    at ``cross_engine.py``:3973-4044).

    **Setup (Python-side):**
      * p0 has The Seriema on the battlefield; p0's library is EMPTY
        (the no-match shuffle-only case the probe verifies --
        production library-non-empty fetches are gated by the agent
        picker substrate, separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "search_library_for_card", "filter_name":
        "legendary_creature", "max_mv": 0, "may_fail": False}``
        translates to a
        ``SearchLibraryForCard(filter_name='legendary_creature',
        max_mv=0, may_fail=False)`` instance.
      * The triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * With p0's library EMPTY, the resolve appends ONE log line
        (the "no legendary_creature found" diagnostic) and calls
        ``shuffle_library`` (a no-op on empty); hand stays empty,
        library stays empty.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.search import (
        SearchLibraryForCard, SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed The Seriema printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("The Seriema")
    if real is None:
        pytest.skip("The Seriema absent from active CardSource")
    assert "Artifact" in real.card_types, (
        "The Seriema must be an Artifact"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "The Seriema must have an ENTERS triggered ability"
    )
    assert isinstance(enters_ta.effect, SearchLibraryForCard), (
        f"The Seriema ENTERS effect must be SearchLibraryForCard; "
        f"got {type(enters_ta.effect).__name__}"
    )
    # Pin the specific parameterization (the load-bearing "this card
    # carries THIS shape" assertion).
    assert enters_ta.effect.filter_name == "legendary_creature", (
        f"The Seriema ENTERS effect must have "
        f"filter_name='legendary_creature'; got "
        f"{enters_ta.effect.filter_name!r}"
    )
    assert enters_ta.effect.max_mv == 0, (
        f"The Seriema ENTERS effect must have max_mv=0; got "
        f"{enters_ta.effect.max_mv}"
    )
    assert enters_ta.effect.may_fail is False, (
        f"The Seriema ENTERS effect must have may_fail=False; got "
        f"{enters_ta.effect.may_fail}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "search_library_for_card",
            "filter_name": "legendary_creature",
            "max_mv": 0,
            "may_fail": False,
        }
    )
    assert isinstance(bridged, SearchLibraryForCard), (
        f"Bridge arm 'search_library_for_card' must round-trip to "
        f"SearchLibraryForCard; got {type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"The Seriema ENTERS effect must be byte-equal to the "
        f"bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes / parameterizations
    #    (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, SearchLibraryForBasicLandTapped), (
        "SearchLibraryForCard must NOT collapse to "
        "SearchLibraryForBasicLandTapped (the sibling library-search "
        "effect class for basic-land fetching to battlefield; "
        "SearchLibraryForCard fetches to hand)."
    )
    # Round-trip an alternative parameterization to ensure the fields
    # are genuinely round-tripped (not stripped).
    other = _ta_dict_to_python_effect(
        {
            "kind": "search_library_for_card",
            "filter_name": "basic_land",
            "max_mv": 0,
            "may_fail": True,
        }
    )
    assert other.filter_name == "basic_land", (
        f"Sibling round-trip must preserve filter_name='basic_land'; "
        f"got {other.filter_name!r}"
    )
    assert other.may_fail is True, (
        "Sibling round-trip must preserve may_fail=True (the "
        "Spineseeker shape)"
    )
    assert bridged != other, (
        "The Seriema's (legendary_creature, may_fail=False) shape "
        "must NOT collapse to Spineseeker's (basic_land, "
        "may_fail=True) shape"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: empty-
    #    library shuffle-only short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat The Seriema on p0's battlefield.
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
    p0_hand_before = list(py.players[0].hand)
    p0_lib_before = list(py.players[0].library)

    # ------------------------------------------------------------------
    # 5. resolve: empty-library shuffle-only path.  The resolve's
    #    empty-options branch at search.py:91-97 appends one log
    #    diagnostic ("no legendary_creature found") + calls
    #    shuffle_library (a no-op on empty list).  Hand stays empty,
    #    library stays empty.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    # Exactly ONE log line appended (the "no <filter_name> found"
    # diagnostic).  This is the load-bearing observable distinct from
    # the no-op probes -- byte-equality includes log emission.
    assert len(py.log) == pre_log_len + 1, (
        f"The Seriema: empty-library resolve must append exactly ONE "
        f"log line (the 'no legendary_creature found' diagnostic at "
        f"search.py:92-95); got log_len={len(py.log)} (expected "
        f"{pre_log_len + 1})"
    )
    assert "no legendary_creature" in py.log[-1], (
        f"The Seriema: empty-library log message must mention "
        f"'no legendary_creature'; got {py.log[-1]!r}"
    )
    assert py.battlefield == bf_before, (
        "The Seriema: empty-library resolve must NOT mutate the "
        "battlefield"
    )
    assert py.players[0].hand == p0_hand_before, (
        "The Seriema: empty-library resolve must NOT add cards to "
        "the controller's hand (no options to fetch)"
    )
    assert py.players[0].library == p0_lib_before, (
        "The Seriema: empty-library resolve must NOT mutate the "
        "library (shuffle is a no-op on empty)"
    )
    assert source in py.battlefield, (
        "The Seriema: source must remain on the battlefield "
        "post-resolve"
    )

    py.resolving_source = None


# ---------------------------------------------------------------------------
# Probe 3 -- Optimistic Scavenger: Creature ENTERS triggered ->
#   PutPlusOneCounterOnTargetCreature(amount=1, attacking_only=False).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Optimistic
#      Scavenger")`` returns the parsed CardPrinting (Creature).
#   2. The ENTERS triggered ability's effect is a
#      ``PutPlusOneCounterOnTargetCreature(amount=1)`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``PutPlusOneCounterOnTargetCreature(amount=1)`` instance.
#   4. Distinctness from the ``attacking_only=True`` Hospital Room
#      variant is preserved (regression guard).
#   5. Python's ``resolve`` path with empty targets is a silent
#      no-op (the empty-targets short-circuit at
#      ``effects/generic/counters.py``:54-55; ``if not targets: return``).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_optimistic_scavenger_parity():
    """**GENUINE real-EoE cross-engine probe -- Optimistic Scavenger
    (round 35 IIII, Creature ENTERS ->
    PutPlusOneCounterOnTargetCreature(amount=1, attacking_only=
    False)).**

    Drives the **real parsed Optimistic Scavenger printing** through
    the Python-side ``PutPlusOneCounterOnTargetCreature`` resolve
    path, validating the empty-targets silent-no-op short-circuit
    (the resolve's empty-targets branch at
    ``effects/generic/counters.py``:54-55; ``if not targets: return``).
    Pairs the parse + bridge round-trip verification with the live
    Python resolve smoke, the same parse + bridge-round-trip + Python-
    side resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD +
    EEEE + FFFF + GGGG + HHHH established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding the Optimistic Scavenger slug to the Effect+bridge round-
    trip of its ENTERS ``PutPlusOneCounterOnTargetCreature(amount=1)``
    shape on the REAL parsed EoE printing.  Complements:
      * Drix Fatemaker (PROBED via the smoke-file probe) pins the
        bare ``PutPlusOneCounterOnTargetCreature(amount=1)`` shape on
        ENTERS with the ``IsSelf`` trigger predicate.
      * Mm'menon, Uthros Exile (PROBED) pins the same effect class
        with the ``Subject(IsArtifact) & Controlled(YOU)`` trigger
        predicate.
      * Honor (PROBED) drives the same effect class as a SPELL --
        DIFFERENT event.
      * Selfcraft Mechan / Shrewd Storyteller pin other event
        variants.
    The PROBED-tier classifier credits per-slug (``_smoke_probed_cards``
    + ``_probe_module_probed_cards`` both scan
    ``test_cross_engine_real_eoe_<slug>_parity`` function names);
    Optimistic Scavenger is currently covered-by-construction but has
    no slug-keyed probe -- IIII closes the attribution gap.

    **Bridge arm exercised:**
    ``put_plus_one_counter_on_target_creature`` (matching Rust's
    ``Effect::PutPlusOneCounterOnTargetCreature { amount, attacking_only
    }`` -- PPP Pin 2 / 10th Rust slice; bridge dispatch at
    ``cross_engine.py``:9542-9591).

    **Setup (Python-side):**
      * p0 has Optimistic Scavenger on the battlefield; no other
        creatures (the empty-targets case the probe verifies --
        production target-bearing cases are gated by the agent
        target-picker substrate, separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "put_plus_one_counter_on_target_creature",
        "amount": 1}`` translates to a
        ``PutPlusOneCounterOnTargetCreature(amount=1,
        attacking_only=False)`` instance.
      * The Creature's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * ``requires_target() is True`` (the oracle "target creature").
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
    # 1. Verify the genuine parsed Optimistic Scavenger printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Optimistic Scavenger")
    if real is None:
        pytest.skip("Optimistic Scavenger absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Optimistic Scavenger must be a Creature"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Optimistic Scavenger must have an ENTERS triggered ability"
    )
    assert isinstance(
        enters_ta.effect, PutPlusOneCounterOnTargetCreature,
    ), (
        f"Optimistic Scavenger ENTERS effect must be "
        f"PutPlusOneCounterOnTargetCreature; got "
        f"{type(enters_ta.effect).__name__}"
    )
    # Pin the specific parameterization.
    assert enters_ta.effect.amount == 1, (
        f"Optimistic Scavenger ENTERS effect must have amount=1; got "
        f"{enters_ta.effect.amount}"
    )
    assert enters_ta.effect.attacking_only is False, (
        f"Optimistic Scavenger ENTERS effect must have "
        f"attacking_only=False (bare target-creature, not "
        f"attacking-only); got {enters_ta.effect.attacking_only}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_target_creature",
            "amount": 1,
        }
    )
    assert isinstance(bridged, PutPlusOneCounterOnTargetCreature), (
        f"Bridge arm 'put_plus_one_counter_on_target_creature' must "
        f"round-trip to PutPlusOneCounterOnTargetCreature; got "
        f"{type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Optimistic Scavenger ENTERS effect must be byte-equal to "
        f"the bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
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
    # Distinctness from the attacking_only=True Hospital Room shape.
    attacking_variant = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_target_creature",
            "amount": 1,
            "attacking_only": True,
        }
    )
    assert attacking_variant.attacking_only is True, (
        "Sibling round-trip must preserve attacking_only=True (the "
        "Hospital Room half shape)"
    )
    assert bridged != attacking_variant, (
        "Optimistic Scavenger's (amount=1, attacking_only=False) "
        "shape must NOT collapse to Hospital Room's "
        "(amount=1, attacking_only=True) shape"
    )
    assert bridged.requires_target() is True, (
        "PutPlusOneCounterOnTargetCreature must require a target "
        "(the oracle 'target creature')"
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

    # Seat Optimistic Scavenger on p0's battlefield.
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
    # 5. resolve: empty-targets silent-no-op.  The resolve's
    #    empty-targets branch at counters.py:54-55 (``if not targets:
    #    return``) leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Optimistic Scavenger: empty-targets resolve must NOT "
        f"append a log line (the resolve's empty-targets short-"
        f"circuit at counters.py:54-55); got log_len={len(py.log)} "
        f"(expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Optimistic Scavenger: empty-targets resolve must NOT "
        "mutate the battlefield"
    )
    assert source.plus_one_counters == source_counters_before, (
        f"Optimistic Scavenger: empty-targets resolve must NOT add "
        f"+1/+1 counters to the source; got "
        f"counters={source.plus_one_counters} (expected "
        f"{source_counters_before})"
    )
    assert source in py.battlefield, (
        "Optimistic Scavenger: source must remain on the "
        "battlefield post-resolve"
    )

    py.resolving_source = None


# ---------------------------------------------------------------------------
# Probe 4 -- Command Bridge: Land ENTERS triggered ->
#   SacrificeSelfUnlessTapPermanent() (unit variant).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Command Bridge")``
#      returns the parsed CardPrinting (Land).
#   2. The ENTERS triggered ability's effect is a
#      ``SacrificeSelfUnlessTapPermanent()`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``SacrificeSelfUnlessTapPermanent()`` instance (unit variant
#      -- no fields).
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against effect-class collapse).
#   5. Python's ``resolve`` path with ``resolving_source=None`` is a
#      silent no-op (the no-source short-circuit at
#      ``effects/combinators.py``:121-123).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_command_bridge_parity():
    """**GENUINE real-EoE cross-engine probe -- Command Bridge
    (round 35 IIII, Land ENTERS -> SacrificeSelfUnlessTapPermanent()).**

    Drives the **real parsed Command Bridge printing** through the
    Python-side ``SacrificeSelfUnlessTapPermanent`` resolve path,
    validating the no-source silent-no-op short-circuit (the
    resolve's early-return at ``effects/combinators.py``:121-123 when
    ``state.resolving_source is None``).  Pairs the parse + bridge
    round-trip verification with the live Python resolve smoke, the
    same parse + bridge-round-trip + Python-side resolve idiom DDD
    slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD + EEEE + FFFF + GGGG +
    HHHH established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe of
    the dedicated bespoke ``SacrificeSelfUnlessTapPermanent`` effect
    class on the REAL parsed Command Bridge EoE printing.  Command
    Bridge is the ONLY EoE consumer of this effect class (the
    HIGHEST-deck-count BLOCKED-genuinely_missing closure on the
    ``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`` list at the time
    of the 20th Rust slice / VVV Pin 2; 24,522 17lands decks).
    Complements:
      * Existing downstream tests at
        ``tests/test_probe_vvv_downstream.py`` /
        ``tests/test_command_bridge.py`` cover the resolve mechanics
        on SYNTHETIC carriers built via
        ``register_and_inject_object``; those tests are NOT credited
        by the PROBED-tier classifier because their function names
        do not start with the ``test_cross_engine_real_eoe_`` prefix
        the slug scanner requires.

    Command Bridge is a Land carrier; HHHH's drop list cited "Lands
    (activated-ability surface)" generically as a skip reason, but
    Command Bridge is a LAND-shape ETB whose TRIGGERED ability is
    the load-bearing parity ask (separate from its mana-ability
    activated surface which stays the dropped surface).  The PROBED-
    tier classifier credits the card at the per-card slug level once
    every Effect it emits has a covered Rust variant + bridge arm,
    AND a slug-keyed probe pins the card.  Command Bridge meets
    both bars after this probe.

    **Bridge arm exercised:**
    ``sacrifice_self_unless_tap_permanent`` (matching Rust's
    ``Effect::SacrificeSelfUnlessTapPermanent`` -- 20th Rust slice /
    VVV Pin 2 unit-variant; bridge dispatch at
    ``cross_engine.py``:8382-8422).

    **Setup (Python-side):**
      * p0 has Command Bridge on the battlefield with
        ``resolving_source=None`` (the silent-no-op case the probe
        verifies -- production source-bound cases are gated by the
        broader PendingDecision::TapPermanentChoice substrate,
        separate lane).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "sacrifice_self_unless_tap_permanent"}`` translates
        to a ``SacrificeSelfUnlessTapPermanent()`` instance.
      * The Land's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * With ``resolving_source=None``, the resolve is a no-op:
        log unchanged, battlefield unchanged, source remains on bf.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import (
        SacrificeSelfUnlessTapPermanent, SacrificeSelfUnlessVoidActive,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Command Bridge printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Command Bridge")
    if real is None:
        pytest.skip("Command Bridge absent from active CardSource")
    assert "Land" in real.card_types, (
        "Command Bridge must be a Land"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Command Bridge must have an ENTERS triggered ability "
        "(the bespoke SacrificeSelfUnlessTapPermanent class encodes "
        "the ETB body)"
    )
    assert isinstance(enters_ta.effect, SacrificeSelfUnlessTapPermanent), (
        f"Command Bridge ENTERS effect must be "
        f"SacrificeSelfUnlessTapPermanent; got "
        f"{type(enters_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "sacrifice_self_unless_tap_permanent"}
    )
    assert isinstance(bridged, SacrificeSelfUnlessTapPermanent), (
        f"Bridge arm 'sacrifice_self_unless_tap_permanent' must "
        f"round-trip to SacrificeSelfUnlessTapPermanent; got "
        f"{type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert enters_ta.effect == bridged, (
        f"Command Bridge ENTERS effect must be byte-equal to the "
        f"bridged Effect; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, SacrificeSelfUnlessVoidActive), (
        "SacrificeSelfUnlessTapPermanent must NOT collapse to "
        "SacrificeSelfUnlessVoidActive (the sibling sacrifice-unless "
        "effect class with a Void-active gate instead of a tap-"
        "permanent gate; different cost shape -- Command Bridge "
        "demands a tap-permanent payment, Chorale of the Void demands "
        "Void-active state)."
    )
    assert bridged.requires_target() is False, (
        "SacrificeSelfUnlessTapPermanent must NOT require a target "
        "(the tap-permanent payment is a cost-time decision, not a "
        "targeted effect; the source is resolved via "
        "state.resolving_source)"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state: no-source
    #    silent-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat Command Bridge on p0's battlefield as a "bystander" -- it's
    # NOT the resolving source for this probe (we explicitly verify
    # the no-source short-circuit).
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # CRITICAL: resolving_source is None (the no-source short-circuit
    # case).  The resolve's early-return at combinators.py:121-123
    # makes this a pure no-op regardless of battlefield contents.
    py.resolving_source = None
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)
    p0_gy_before = list(py.players[0].graveyard)

    # ------------------------------------------------------------------
    # 5. resolve: no-source silent-no-op.  The resolve's early-return
    #    at combinators.py:121-123 (``if source is None: return``)
    #    leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Command Bridge: no-source resolve must NOT append a log "
        f"line (the resolve's no-source short-circuit at "
        f"combinators.py:121-123); got log_len={len(py.log)} "
        f"(expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Command Bridge: no-source resolve must NOT mutate the "
        "battlefield (no source to sacrifice or keep)"
    )
    assert py.players[0].graveyard == p0_gy_before, (
        "Command Bridge: no-source resolve must NOT route anything "
        "to the graveyard (the sacrifice path requires source)"
    )
    assert source in py.battlefield, (
        "Command Bridge: bystander source must remain on the "
        "battlefield post-resolve (the no-source path doesn't touch "
        "it)"
    )
    assert source.tapped is False, (
        "Command Bridge: bystander source must NOT be tapped by the "
        "no-source resolve (the resolve short-circuits before any "
        "tap dispatch)"
    )
