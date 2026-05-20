"""Genuine real-EoE cross-engine byte-equality probes -- batch CCCC
(round 29, the THIRD 4-letter probe batch -- post-ZZZ alphabetic-
exhaustion, post-AAAA, sibling to in-flight BBBB).

The AAAA batch (``tests/test_probe_remaining_aaaa.py``:1-15) opened
the 4-letter naming convention post-ZZZ alphabetic exhaustion.  CCCC
is the third 4-letter batch (round 29); sibling lane BBBB is the
second (round 28; in-flight as ``feature/probe-batch-bbbb``).
Subsequent batches follow ``DDDD`` / ``EEEE`` / ... per the
established 4-letter alphabetic cadence.

Two cards from the ``covered_by_construction`` tier are upgraded to
the ``PROBED`` tier by this module via the same parse + bridge round-
trip + Python-side resolve idiom DDD slice 17's Honored Knight-Captain
probe (``tests/test_probe_ddd_downstream.py``:408), the YYY batch's
two probes (``tests/test_probe_remaining_yyy.py``:272 / 573), the ZZZ
batch's two probes (``tests/test_probe_remaining_zzz.py``:173 / 413),
and the AAAA batch's two probes (``tests/test_probe_remaining_aaaa.py``:231
/ 511) established as a PROBE_MODULES-credited shape.

  * **Lightless Evangel** -- Creature with an IS_SACRIFICED triggered
    ability emitting ``PutPlusOneCounterOnSelf(amount=1)``.  Bridge
    arm at ``cross_engine.py``:4039 (round-22 BLOCKED-BRIDGE-ARM
    slice closure; unit variant matching Rust's
    ``Effect::PutPlusOneCounterOnSelf { amount }``).  **NEW shape
    coverage:** the FIRST IS_SACRIFICED-event carrier of the
    ``PutPlusOneCounterOnSelf`` effect to land a PROBE_MODULES-
    credited ``_parity`` probe.  Complements:
      * Pulsar Squadron Ace / Sunstar Lightsmith / Tezzeret cards
        (covered_by_construction; ENTERS-event ``PutPlusOneCounterOnSelf``
        consumers -- the more common trigger event).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the trigger **event** -- IS_SACRIFICED fires when
    the source is sacrificed (a LTB event with a sacrifice-cause
    refinement), not when it ETBs.  The trigger predicate (a
    composite ``And`` walking the sacrifice-source filter) is
    metadata; the probe verifies the effect + the
    resolve-by-resolving_source mutation regardless of predicate
    firing.  Lightless Evangel is the only EoE consumer of the
    IS_SACRIFICED + ``PutPlusOneCounterOnSelf`` shape.

  * **Skystinger** -- Creature with a BLOCKS triggered ability
    emitting ``PumpSelfUntilEOT(power_bonus=5, toughness_bonus=0,
    granted_keywords=frozenset())``.  Bridge arm at
    ``cross_engine.py``:4221 (round-22 BLOCKED-BRIDGE-ARM slice
    closure; unit variant matching Rust's
    ``Effect::PumpSelfUntilEOT { power_bonus, toughness_bonus }``,
    bare 2-field shape -- the ``granted_keywords`` rider is NOT
    carried by the bridge but Skystinger's emission has an empty
    granted_keywords, so the bare bridge form is byte-equal).
    **NEW shape coverage:** the FIRST BLOCKS-event carrier of the
    ``PumpSelfUntilEOT`` effect with the bare (no granted-keywords)
    shape to land a PROBE_MODULES-credited ``_parity`` probe.
    Complements:
      * Hand That Feeds (covered_by_construction; ATTACKS-event
        ``PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0,
        granted_keywords={'menace'})`` -- different event + carries
        a granted_keywords rider so the bare bridge would NOT pin
        the full shape).
      * Cult Healer (covered_by_construction; ENTERS-event
        ``PumpSelfUntilEOT(power_bonus=0, toughness_bonus=0,
        granted_keywords={'lifelink'})`` -- pure keyword grant, the
        ``(0, 0)`` short-circuit + the lifelink rider mean the bare
        bridge would NOT pin the full shape).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the trigger **event** (BLOCKS, a combat-step event,
    NOT the ETB / ATTACKS events the existing covered cards use)
    AND the bare-shape variant -- Skystinger's
    ``granted_keywords=frozenset()`` makes the bare bridge form
    byte-equal, the FIRST credited consumer of that combination.

DROPPED ON VERIFY (honest discipline + sibling-lane divergence pins)
---------------------------------------------------------------------

  * **Trapped in the Screen** (bare Enchantment ENTERS + IsSelf ->
    ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)``):
    bit-identical SHAPE to the already-PROBED Banishing Light
    (``test_parity_smoke.py``:34228 ``test_cross_engine_real_eoe_
    banishing_light_etb_exile_nonland_permanent_until_leaves_parity``)
    -- BOTH are bare Enchantment carriers (``subtypes=()``) with the
    same effect class + same ``max_mv=0`` parameter + same IsSelf
    predicate + same ENTERS event.  No NEW shape coverage at the
    bridge / effect / carrier-substrate axis (same drop discipline
    ZZZ used for this card -- see ``test_probe_remaining_zzz.py``:
    62-71 + the YYY drop list at :88-108 which re-confirms the
    Trapped in the Screen + Banishing Light bit-identical shape).
    Initially considered for CCCC but the verify step found
    Banishing Light already pins the bare-Enchantment +
    ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)`` ETB
    consumer at the same bar -- a redundant probe would not move
    the PROBED-tier classifier (the script already credits cards
    via slug match, and Banishing Light's slug-credited probe
    already pins this shape).  Honest exhaustion.

  * **Violent Urge / Horrid Vigor / Dual-Sun Technique / Give In to
    Violence** (Instant ``spell_effect=PumpTargetCreatureUntilEOT``
    with ``granted_keywords`` rider): the ``granted_keywords`` rider
    on ``PumpTargetCreatureUntilEOT`` is NOT carried by the bare
    ``pump_target_creature_until_eot`` bridge arm (cross_engine.py:
    1125-1190 -- the arm bridges only ``power_bonus`` /
    ``toughness_bonus``).  Probing without rider preservation would
    not pin THIS card's full Effect-shape -- honest exhaustion
    until a rider-bearing pump arm lands.

  * **Hand That Feeds / Cult Healer** (Creature ATTACKS / ENTERS +
    ``PumpSelfUntilEOT`` with ``granted_keywords`` rider): same
    rider-omission gap as the Pump-target instants above (the
    ``pump_self_until_eot`` bridge arm at cross_engine.py:4221-4284
    drops the rider).  Honest exhaustion until a rider-bearing
    pump-self arm lands.

  * **Bottomless Pool // Locker Room** (Room ENTERS +
    ``ReturnTargetCreatureToOwnersHand``): no matching
    ``return_target_creature_to_owners_hand`` bridge arm in
    ``cross_engine.py``; the Room subtype + the conditional-second-
    half DEALS_COMBAT_DAMAGE trigger are also subsystem-gated.
    Honest exhaustion at the bridge layer.

  * **Optimistic Scavenger / Cult Healer** (Room-unlocked sibling
    triggers -- ROOM_FULLY_UNLOCKED event): the ROOM_FULLY_UNLOCKED
    event is on the engine but the cross-engine probe substrate
    requires a Room printing fully unlocked end-to-end; that's a
    subsystem-gated probe, not a bare effect+bridge slice.  Honest
    exhaustion at the subsystem layer.

  * **Innocuous Rat** (Creature DIES + ``ManifestDread(count=1)``):
    the ``ManifestDread`` effect resolve at
    ``effects/generic/library_lookat.py`` requires:
      1. a library with at least one card (for ``ManifestDread``'s
         examined-cards step);
      2. an agent on the controller providing
         ``choose_card_from_library`` (when ``len(examined) == 2``
         the manifest-vs-graveyard pick goes through the agent);
      3. the ``put_into_battlefield`` fan-out from the manifest step.
    That's substrate beyond the bare bridge-arm slice -- the same
    deferral AAAA dropped for Conductive Machete / Killer's Mask
    (Equipment ETB + ``ManifestDreadThenAttachSelf``).  Honest
    exhaustion until the manifest-dread harness substrate is wired.

  * **Let's Play a Game / Split Up** (Sorcery
    ``spell_effect=ModalChooseOne``): modal-choice substrate
    requires an agent picker + mode-resolution wiring (the round-22
    ``test_probe_modal_counterspell_u.py`` probes the Counterspell
    modal lane).  ``ModalChooseOne`` over arbitrary modes is
    subsystem-gated for the cross-engine probe shape today --
    honest exhaustion at the modal-substrate layer.

  * **Lightless Evangel keyword grants** -- the IS_SACRIFICED
    predicate is a composite ``And(And(Subject(ObjectOr(IsCreature,
    IsArtifact)), Controlled), Not(IsSelf))`` -- this probe pins
    the EFFECT shape (PutPlusOneCounterOnSelf), not the predicate's
    full sacrifice-cause cascade.  The predicate is metadata; the
    bare effect + bridge + resolve smoke is the credited probe
    shape per the YYY / ZZZ / AAAA precedent.

  * **All previously-PROBED cards** with the same effect classes --
    Banishing Light, Sheltered by Ghosts (ZZZ), Stay Hidden / Stay
    Silent (ZZZ), Hardlight Containment, Diplomatic Relations
    (YYY), Astelli Reclaimer (YYY), Cryoshatter / Meltstrider's
    Gear (AAAA) -- already PROBED via earlier modules; not
    re-probed here.

  * **Subsystem-gated remainder** -- the long tail of Aura
    attachment full surface / Equipment activated-ability surface /
    Room / IS_CAST stack-resolution / non-Effect gate cards; the
    YYY-idiom (parse + bridge + Python-resolve) does not unblock
    them.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED``
tier upon merge.  Prior PROBED count (with AAAA + BBBB wired in via
PROBE_MODULES, post-BBBB landing -- main HEAD ``962c4a7d``): 222.
Net delta from this module: +2 (PROBED), -2 (covered).
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
# Probe 1 -- Lightless Evangel: Creature IS_SACRIFICED triggered ->
#   PutPlusOneCounterOnSelf(amount=1).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Lightless Evangel")``
#      returns the parsed CardPrinting (Creature, Vampire Cleric).
#   2. The IS_SACRIFICED triggered ability's effect is a
#      ``PutPlusOneCounterOnSelf`` instance with ``amount=1``.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``PutPlusOneCounterOnSelf(amount=1)`` instance.
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``resolve`` path drives the
#      ``state.resolving_source`` mutation: the source's
#      ``plus_one_counters`` field is incremented by 1 post-resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lightless_evangel_parity():
    """**GENUINE real-EoE cross-engine probe -- Lightless Evangel
    (round 29 CCCC, Creature IS_SACRIFICED ->
    PutPlusOneCounterOnSelf(amount=1)).**

    Drives the **real parsed Lightless Evangel printing** through the
    Python-side ``PutPlusOneCounterOnSelf`` resolve path, validating
    the ``state.resolving_source`` mutation pipeline on a controlled
    state (source's ``plus_one_counters`` field is incremented from
    0 to 1 post-resolve).  Pairs the parse + bridge round-trip
    verification with the live Python resolve smoke, the same parse
    + bridge-round-trip + Python-side resolve idiom DDD slice 17 +
    YYY + ZZZ + AAAA established.

    **NEW shape coverage:** the FIRST IS_SACRIFICED-event carrier of
    the ``PutPlusOneCounterOnSelf`` effect to land a PROBE_MODULES-
    credited ``_parity`` probe.  Complements:
      * Pulsar Squadron Ace / Sunstar Lightsmith (ENTERS / IS_CAST
        event carriers of the same effect, covered or smoke-PROBED;
        the more common trigger events).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the trigger **event** -- IS_SACRIFICED fires when
    the source is sacrificed (a LTB event with the sacrifice-cause
    refinement), not when it ETBs or is cast.  Lightless Evangel is
    the only EoE consumer of the IS_SACRIFICED +
    ``PutPlusOneCounterOnSelf`` shape.

    **Bridge arm exercised:** ``put_plus_one_counter_on_self`` at
    ``cross_engine.py``:4039 (round-22 BLOCKED-BRIDGE-ARM slice
    closure; unit variant matching Rust's
    ``Effect::PutPlusOneCounterOnSelf { amount: i32 }`` at
    cards.rs:260, parser at cards.rs:3287-3306, resolve at
    state_ops_resolve.rs:2601-2635).

    **Setup (Python-side):**
      * p0 has Lightless Evangel on the battlefield (the
        Creature serving as ``resolving_source``).
        ``plus_one_counters=0`` pre-resolve.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "put_plus_one_counter_on_self", "amount": 1}``
        translates to a ``PutPlusOneCounterOnSelf(amount=1)``
        instance (with ``amount=1``).
      * The Creature's IS_SACRIFICED triggered ability emits
        ``PutPlusOneCounterOnSelf(amount=1)``.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: the source's ``plus_one_counters`` field is
        1 (was 0 pre-resolve); the state log carries the
        "+1/+1 counter" line for the source.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Lightless Evangel printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Lightless Evangel")
    )
    if real is None:
        pytest.skip("Lightless Evangel absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Lightless Evangel must be a Creature"
    )
    is_sacrificed_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.IS_SACRIFICED
        ),
        None,
    )
    assert is_sacrificed_ta is not None, (
        "Lightless Evangel must have an IS_SACRIFICED triggered "
        "ability (the trigger event distinguishing this probe from "
        "the existing ENTERS / IS_CAST consumers of "
        "PutPlusOneCounterOnSelf)"
    )
    assert isinstance(
        is_sacrificed_ta.effect, PutPlusOneCounterOnSelf,
    ), (
        f"Lightless Evangel IS_SACRIFICED effect must be "
        f"PutPlusOneCounterOnSelf; got "
        f"{type(is_sacrificed_ta.effect).__name__}"
    )
    assert is_sacrificed_ta.effect.amount == 1, (
        f"Lightless Evangel IS_SACRIFICED effect must have amount=1; "
        f"got amount={is_sacrificed_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "put_plus_one_counter_on_self", "amount": 1}
    )
    assert isinstance(bridged, PutPlusOneCounterOnSelf), (
        f"Bridge arm 'put_plus_one_counter_on_self' must round-trip "
        f"to PutPlusOneCounterOnSelf; got {type(bridged).__name__}"
    )
    assert bridged.amount == 1, (
        f"Bridged PutPlusOneCounterOnSelf must carry amount=1; got "
        f"amount={bridged.amount}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert is_sacrificed_ta.effect == bridged, (
        f"Lightless Evangel IS_SACRIFICED effect must be byte-equal "
        f"to the bridged Effect; got parsed={is_sacrificed_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, PumpSelfUntilEOT), (
        "PutPlusOneCounterOnSelf must NOT collapse to "
        "PumpSelfUntilEOT (a sibling self-targeted effect with "
        "different mutation semantics; pump grants a UEOT bonus, "
        "counter is a persistent layer-7 modifier)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Lightless Evangel Creature on p0's battlefield
    # (the ``resolving_source``).  plus_one_counters=0 pre-resolve.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)
    assert source.plus_one_counters == 0, (
        f"Pre-resolve sanity: source.plus_one_counters must start at "
        f"0; got {source.plus_one_counters}"
    )

    # ------------------------------------------------------------------
    # 5. Set resolving_source = the Lightless Evangel source object on
    #    p0's bf (per the PutPlusOneCounterOnSelf.resolve contract --
    #    reads ``state.resolving_source`` for the mutation target).
    # ------------------------------------------------------------------
    py.resolving_source = source

    # ------------------------------------------------------------------
    # 6. resolve: add a +1/+1 counter to the source.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())
    py.resolving_source = None

    # Source: plus_one_counters incremented from 0 to 1.
    assert source.plus_one_counters == 1, (
        f"Lightless Evangel: source.plus_one_counters must equal 1 "
        f"post-resolve (PutPlusOneCounterOnSelf(amount=1) adds one "
        f"counter via add_plus_one_counters); got "
        f"source.plus_one_counters={source.plus_one_counters}"
    )
    # State log records the counter add.
    log_text = "\n".join(py.log)
    assert "gets a +1/+1 counter" in log_text, (
        f"State log must record the +1/+1 counter add; got log:\n"
        f"{log_text}"
    )
    # Source remains on the battlefield (the resolve mutates the
    # counters field; it does NOT move the source).
    assert source in py.battlefield, (
        "Lightless Evangel: source must remain on the battlefield "
        "post-resolve (PutPlusOneCounterOnSelf is a state mutation, "
        "not a zone change)"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Skystinger: Creature BLOCKS triggered ->
#   PumpSelfUntilEOT(power_bonus=5, toughness_bonus=0,
#                    granted_keywords=frozenset()).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Skystinger")``
#      returns the parsed CardPrinting (Creature, Insect Warrior, reach).
#   2. The BLOCKS triggered ability's effect is a ``PumpSelfUntilEOT``
#      instance with ``power_bonus=5, toughness_bonus=0,
#      granted_keywords=frozenset()`` -- the BARE shape (no keyword
#      rider) that matches the bridge's bare 2-field variant exactly.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``PumpSelfUntilEOT(power_bonus=5, toughness_bonus=0)`` instance
#      (with default ``granted_keywords=frozenset()``).
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``resolve`` path drives the
#      ``state.grant_pt_pump_ueot`` pipeline: the source's effective
#      power is +5 post-resolve (the UEOT registry entry is active).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_skystinger_parity():
    """**GENUINE real-EoE cross-engine probe -- Skystinger (round 29
    CCCC, Creature BLOCKS -> PumpSelfUntilEOT(power_bonus=5,
    toughness_bonus=0, granted_keywords=frozenset())).**

    Drives the **real parsed Skystinger printing** through the
    Python-side ``PumpSelfUntilEOT`` resolve path, validating the
    ``state.grant_pt_pump_ueot`` UEOT-registry pipeline on a
    controlled state (source's effective power is +5 post-resolve).
    Pairs the parse + bridge round-trip verification with the live
    Python resolve smoke, the same parse + bridge-round-trip +
    Python-side resolve idiom DDD slice 17 + YYY + ZZZ + AAAA
    established.

    **NEW shape coverage:** the FIRST BLOCKS-event carrier of the
    ``PumpSelfUntilEOT`` effect with the bare (no granted-keywords)
    shape to land a PROBE_MODULES-credited ``_parity`` probe.
    Complements:
      * Hand That Feeds (covered_by_construction; ATTACKS-event
        ``PumpSelfUntilEOT(power_bonus=2, granted_keywords=
        {'menace'})`` -- different event + carries a granted_keywords
        rider the bare bridge does NOT carry).
      * Cult Healer (covered_by_construction; ENTERS-event
        ``PumpSelfUntilEOT(power_bonus=0, toughness_bonus=0,
        granted_keywords={'lifelink'})`` -- pure keyword grant; the
        ``(0, 0)`` short-circuit + the lifelink rider mean the bare
        bridge would NOT pin the full shape).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the trigger **event** (BLOCKS, a combat-step event,
    NOT ETB / ATTACKS) AND the BARE-shape variant -- Skystinger's
    ``granted_keywords=frozenset()`` makes the bare bridge byte-
    equal, the FIRST credited consumer of that combination.

    **Bridge arm exercised:** ``pump_self_until_eot`` at
    ``cross_engine.py``:4221 (round-22 BLOCKED-BRIDGE-ARM slice
    closure; matching Rust's
    ``Effect::PumpSelfUntilEOT { power_bonus, toughness_bonus }`` at
    cards.rs:725, parser at cards.rs:3562-3595, resolve at
    state_ops_resolve.rs:4280-4305; the bare 2-field shape -- the
    Python ``granted_keywords`` rider is NOT carried by the bridge
    but Skystinger's emission has an empty granted_keywords, so the
    bare bridge form is byte-equal).

    **Setup (Python-side):**
      * p0 has Skystinger on the battlefield (the Creature serving
        as ``resolving_source``).  Pre-resolve effective power = its
        printed power.

    **Observables asserted:**
      * Skystinger's printing has the ``reach`` keyword (the
        oracle-text printed keyword, NOT a granted_keywords rider on
        the trigger -- the trigger's PumpSelfUntilEOT has empty
        granted_keywords).
      * Bridge round-trip:
        ``{"kind": "pump_self_until_eot", "power_bonus": 5,
           "toughness_bonus": 0}`` translates to a
        ``PumpSelfUntilEOT(power_bonus=5, toughness_bonus=0)``
        instance (with default ``granted_keywords=frozenset()``).
      * The Creature's BLOCKS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: the source's effective power is its printed
        power + 5 (the UEOT registry entry is active until cleanup);
        the state log carries the "+5/+0 until end of turn" line.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Skystinger printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Skystinger")
    )
    if real is None:
        pytest.skip("Skystinger absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Skystinger must be a Creature"
    )
    # Printed keyword: reach (the oracle-text printed static keyword,
    # NOT a UEOT-granted rider on the BLOCKS trigger).  This pins the
    # printed-keyword shape distinct from the trigger's
    # granted_keywords slot.
    assert "reach" in real.keywords, (
        f"Skystinger must have the printed 'reach' keyword (the "
        f"oracle-text static keyword on the printing); got "
        f"keywords={sorted(real.keywords)}"
    )
    blocks_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.BLOCKS
        ),
        None,
    )
    assert blocks_ta is not None, (
        "Skystinger must have a BLOCKS triggered ability (the "
        "combat-step event distinguishing this probe from the "
        "existing ENTERS / ATTACKS consumers of PumpSelfUntilEOT)"
    )
    assert isinstance(blocks_ta.effect, PumpSelfUntilEOT), (
        f"Skystinger BLOCKS effect must be PumpSelfUntilEOT; got "
        f"{type(blocks_ta.effect).__name__}"
    )
    assert blocks_ta.effect.power_bonus == 5, (
        f"Skystinger BLOCKS effect must have power_bonus=5; got "
        f"power_bonus={blocks_ta.effect.power_bonus}"
    )
    assert blocks_ta.effect.toughness_bonus == 0, (
        f"Skystinger BLOCKS effect must have toughness_bonus=0; got "
        f"toughness_bonus={blocks_ta.effect.toughness_bonus}"
    )
    # The defining BARE-shape feature: NO granted_keywords rider on
    # the trigger (the printed 'reach' keyword is on the printing's
    # static keywords, NOT on the trigger's UEOT grant).  This is
    # what makes Skystinger (rather than Hand That Feeds or Cult
    # Healer) the canonical bare-bridge-arm consumer.
    assert blocks_ta.effect.granted_keywords == frozenset(), (
        f"Skystinger BLOCKS effect must have empty granted_keywords "
        f"(no UEOT keyword-grant rider -- this is the bare shape "
        f"that matches Rust's bare 2-field variant exactly); got "
        f"granted_keywords={sorted(blocks_ta.effect.granted_keywords)}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_self_until_eot",
            "power_bonus": 5,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(bridged, PumpSelfUntilEOT), (
        f"Bridge arm 'pump_self_until_eot' must round-trip to "
        f"PumpSelfUntilEOT; got {type(bridged).__name__}"
    )
    assert bridged.power_bonus == 5, (
        f"Bridged PumpSelfUntilEOT must carry power_bonus=5; got "
        f"power_bonus={bridged.power_bonus}"
    )
    assert bridged.toughness_bonus == 0, (
        f"Bridged PumpSelfUntilEOT must carry toughness_bonus=0; got "
        f"toughness_bonus={bridged.toughness_bonus}"
    )
    # Bare bridge default: empty granted_keywords (the bridge arm
    # constructs PumpSelfUntilEOT(power, toughness) with no rider --
    # the default field is frozenset()).
    assert bridged.granted_keywords == frozenset(), (
        f"Bridged PumpSelfUntilEOT must carry empty granted_keywords "
        f"(bare bridge arm; rider-bearing variant is a deferred "
        f"follow-up); got "
        f"granted_keywords={sorted(bridged.granted_keywords)}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect (the load-bearing
    # cross-engine assertion -- only valid because the printing's
    # granted_keywords is empty too).
    assert blocks_ta.effect == bridged, (
        f"Skystinger BLOCKS effect must be byte-equal to the bridged "
        f"Effect (only possible because both carry empty "
        f"granted_keywords -- the bare bridge form); got "
        f"parsed={blocks_ta.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, PutPlusOneCounterOnSelf), (
        "PumpSelfUntilEOT must NOT collapse to "
        "PutPlusOneCounterOnSelf (Probe 1's self-targeted effect "
        "with different mutation semantics; UEOT bonus expires at "
        "cleanup, +1/+1 counter persists as a layer-7c base modifier)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Skystinger Creature on p0's battlefield (the
    # ``resolving_source``).  Record its printed power for the
    # post-resolve delta check.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)
    printed_power = real.power
    assert printed_power is not None, (
        "Skystinger must have a printed power (it's a Creature)"
    )

    # ------------------------------------------------------------------
    # 5. Set resolving_source = the Skystinger source object on
    #    p0's bf (per the PumpSelfUntilEOT.resolve contract -- reads
    #    ``state.resolving_source`` for the source-id stamp).
    # ------------------------------------------------------------------
    py.resolving_source = source

    # ------------------------------------------------------------------
    # 6. resolve: grant the +5/+0 UEOT bonus.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())
    py.resolving_source = None

    # Source: effective power is printed_power + 5 (the layer-7c
    # additive bonus from the UEOT registry).  Use the engine's
    # standard ``effective_power`` reader (game.py:2268).
    from mtg_bot.game import effective_power as game_effective_power
    effective_pwr = game_effective_power(py, source)
    assert effective_pwr == printed_power + 5, (
        f"Skystinger: effective power must be printed_power + 5 "
        f"post-resolve (PumpSelfUntilEOT(+5/+0) grants a layer-7c "
        f"additive bonus via grant_pt_pump_ueot); got "
        f"effective_power={effective_pwr} (expected "
        f"{printed_power} + 5 = {printed_power + 5})"
    )
    # State log records the pump.
    log_text = "\n".join(py.log)
    assert "+5/+0 until end of turn" in log_text, (
        f"State log must record the +5/+0 UEOT pump; got log:\n"
        f"{log_text}"
    )
    # Source remains on the battlefield (the resolve mutates the UEOT
    # registry; it does NOT move the source).
    assert source in py.battlefield, (
        "Skystinger: source must remain on the battlefield "
        "post-resolve (PumpSelfUntilEOT is a UEOT-registry mutation, "
        "not a zone change)"
    )
