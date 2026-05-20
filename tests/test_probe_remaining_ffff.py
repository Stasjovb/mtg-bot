"""Genuine real-EoE cross-engine byte-equality probes -- batch FFFF
(round 32 relaunch, the SIXTH 4-letter probe batch -- post-DDDD/EEEE
co-merge; this slot was previously claimed by an agent that timed out
at worktree creation, that branch is gone, slot reclaimed fresh).

The AAAA batch (``tests/test_probe_remaining_aaaa.py``) opened the
4-letter naming convention post-ZZZ alphabetic exhaustion.  FFFF is
the sixth 4-letter batch (round 32 relaunch).  Prior 4-letter
batches: AAAA (round 27), BBBB (round 28), CCCC (round 29), DDDD
(round 30 reclaim, main HEAD ``4dac7705`` -- shipped Meltstrider
Eulogist + Balemurk Leech after EEEE pre-empted DDDD's original
Starwinder + Broodguard Elite picks), EEEE (round 31 reclaim, main
HEAD ``04c1f16e`` -- shipped Starwinder + Broodguard Elite).
Subsequent batches follow ``GGGG`` / ``HHHH`` / ... per the
established 4-letter alphabetic cadence.

One card from the ``covered_by_construction`` tier is upgraded to
the ``PROBED`` tier by this module via the same parse + bridge
round-trip + Python-side resolve idiom DDD slice 17's Honored
Knight-Captain probe (``tests/test_probe_ddd_downstream.py``:408),
the YYY batch's two probes (``tests/test_probe_remaining_yyy.py``:
272 / 573), the ZZZ batch's two probes (``tests/test_probe_remaining_
zzz.py``:173 / 413), the AAAA batch's two probes (``tests/test_probe_
remaining_aaaa.py``:231 / 511), the CCCC batch's two probes
(``tests/test_probe_remaining_cccc.py``:223 / 430), the EEEE batch's
two probes (``tests/test_probe_remaining_eeee.py``:245 / 501), and the
DDDD batch's two probes (``tests/test_probe_remaining_dddd.py``)
established as a PROBE_MODULES-credited shape.

  * **Illvoi Operative** -- Creature with an IS_CAST triggered
    ability emitting ``PutPlusOneCounterOnSelf(amount=1)``.  Bridge
    arm at ``cross_engine.py``: ``put_plus_one_counter_on_self``
    (round-21+ closed-vocab effect arm; well-pinned at ENTERS-event
    level by Dockworker Drone / Seedship Agrarian and IS_SACRIFICED-
    event level by Lightless Evangel (CCCC) but **never at IS_CAST
    event level**).  **NEW shape coverage:** the FIRST IS_CAST-event
    carrier of the ``PutPlusOneCounterOnSelf(amount=1)`` effect to
    land a PROBE_MODULES-credited ``_parity`` probe.  Complements:
      * Dockworker Drone (PROBED, ENTERS-event;
        ``tests/test_probe_covered_unprobed_a.py``:272 -- same
        effect class, different trigger event).
      * Seedship Agrarian (PROBED, ENTERS-event -- same effect class,
        different carrier substrate).
      * Lightless Evangel (PROBED via CCCC, IS_SACRIFICED-event;
        ``tests/test_probe_remaining_cccc.py``:223 -- same effect
        class, departure-event variant).
      * Insatiable Skittermaw / Kavaron Skywarden / Interceptor
        Mechan (PROBED via ZZ, BEGINNING_OF_END_STEP-event -- same
        effect class, end-step-tick variant).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the **trigger event** (IS_CAST, a spell-cast event
    on the controller's stack-push, distinct from every other
    PROBED ``PutPlusOneCounterOnSelf`` consumer's resolve-time
    event firing).  Illvoi Operative is the only EoE consumer of
    the IS_CAST + ``PutPlusOneCounterOnSelf`` shape.

    Prior YYY / SSS / UUU drop notes deferred this card on cross-
    engine ``compare_fields`` grounds: the predicate is
    ``And(Controlled(YOU, subject='controller'),
    StateBound(SpellsCastThisTurn(n=2)))`` (a magecraft-style
    second-spell-cast trigger), and the slice-12 ``test_mmm_probe_
    *`` precedent documented an IS_CAST stack-resolution-order
    divergence that breaks full ``compare_fields`` byte-equality
    probes.  The EEEE-idiom (parse + bridge round-trip + Python-
    side resolve, NO cross-engine ``compare_fields``) sidesteps
    that gap entirely: this probe verifies the Effect+bridge byte-
    equality and the Python-side resolve mutation, both of which
    are independent of the IS_CAST stack-resolution mechanism in
    the cross-engine compare path.  This is exactly the same gap-
    bypass DDDD used for Meltstrider Eulogist (HasCounter predicate
    gap) and EEEE used for Starwinder (combat-damage harness gap).

DROPPED ON VERIFY (honest discipline)
---------------------------------------------------------------------

  * **Cosmogrand Zenith / Station Monitor / Sunstar Lightsmith**
    (IS_CAST + StateBound(SpellsCastThisTurn) variants): siblings
    of Illvoi Operative on the same magecraft-style trigger axis,
    BUT their EFFECT classes are blocked:
      - Cosmogrand Zenith: ``ModalChooseOne`` (modal substrate
        requires agent picker + mode-resolution wiring -- same drop
        as CCCC / EEEE Let's Play a Game).
      - Station Monitor: ``CreateToken`` (token-registration
        substrate -- same drop as Weapons Manufacturing / Sami).
      - Sunstar Lightsmith: ``Sequence(PutPlusOneCounterOnSelf(1),
        DrawCards(1))`` (Sequence-wrapper deferral -- same drop as
        EEEE Sunstar Lightsmith line).
    Illvoi Operative is the only one of the four whose IS_CAST
    EFFECT is bare ``PutPlusOneCounterOnSelf`` (no wrapper, no
    token-registration substrate, no modal substrate).

  * **Meltstrider Eulogist / Balemurk Leech** -- already PROBED via
    DDDD (round 30 reclaim, main HEAD ``4dac7705``); not re-probed
    here.

  * **Broodguard Elite / Starwinder** -- already PROBED via EEEE
    (round 31 reclaim, main HEAD ``04c1f16e``); not re-probed here.

  * **Fear of Failed Tests** (Enchantment Creature DEALS_COMBAT_DAMAGE
    + IsSelf -> ``DrawCardsEqualToResolvingCombatDamage()``):
    bit-identical effect-class shape to EEEE-probed Starwinder.
    Same drop discipline as EEEE.

  * **The Seriema** (Spacecraft ENTERS + ``SearchLibraryForCard``):
    Station-subsystem-gated -- the Spacecraft card_type means the
    cross-engine probe substrate is loader-gated by the Station
    subsystem (see ``docs/POOL_PARITY.md`` BLOCKED-subsystem-gated
    Station/Spacecraft row); the bare effect+bridge slice does not
    unblock it.  Same drop discipline as the WWW Station drop list.

  * **Vanilla / keyword-only creatures** (Bedhead Beastie, Cackling
    Slasher, Daggermaw Megalodon, Patched Plaything, Piranha Fly,
    Spectral Snatcher, Shepherding Spirits, Fear of Being Hunted,
    Slavering Branchsnapper): no triggered abilities, no
    spell_effect, only static keywords.  Already represented by
    probed siblings (Hullcarver, Tapestry Warden, Emissary Escort,
    Monoist Sentry); no NEW shape coverage.  Same drop discipline
    as SSS / QQQ / UUU / WWW / YYY / EEEE / DDDD.

  * **Equipment ETBs** (Conductive Machete / Cursed Windbreaker /
    Killer's Mask / Squire's Lightblade / Illvoi Light Jammer /
    Meltstrider's Resolve): blocked by the SSS-round-23 ``put_into_
    battlefield`` non-creature ``summoning_sick=True`` divergence
    pin (``test_probe_remaining_sss.py``:107-148).  Honest
    exhaustion at the bridge-divergence layer.

  * **Hand That Feeds / Flesh Burrower / Cult Healer** (pump
    triggers carrying a ``granted_keywords`` rider): the
    ``pump_target_creature_until_eot`` / ``pump_self_until_eot``
    bridge arms drop the ``granted_keywords`` rider (verified: a
    bridge dict with ``granted_keywords=['lifelink']`` round-trips
    to ``granted_keywords=frozenset()`` -- the rider is silently
    elided).  Honest exhaustion until a rider-bearing pump arm
    lands -- same drop discipline as CCCC at :96-109.

  * **Clammy Prowler** (Creature ATTACKS + IsSelf ->
    GrantUnblockableUEOT(targets=..., attacking_only=True,
    exclude_self=True)): the ``GrantUnblockableUEOT`` effect
    requires target selection (the trigger picks another attacking
    creature) -- the probe shape requires either a controlled-state
    target seat + an agent picker, OR the bridge round-trip alone
    without resolve smoke.  Same DDDD drop list rationale.

  * **Pump-rider spell effects** (Dual-Sun Technique / Horrid Vigor
    / Rig for War / Violent Urge / Give In to Violence): same
    granted_keywords rider-omission gap; SHAPE is also pinned by
    QQQ Dark Endurance.  Honest exhaustion.

  * **Unwanted Remake** (Instant ``spell_effect =
    DestroyTargetCreature``, bare no rider): bit-identical SHAPE
    to the already-PROBED Murder.  Same BBBB drop note.

  * **Break Down the Door / Under the Skin / Innocuous Rat**
    (ManifestDread substrate): blocked per EEEE / CCCC / AAAA --
    ManifestDread resolve requires library + agent picker.

  * **Lithobraking / Unnerving Grasp / Temporal Intervention /
    Let's Play a Game / Split Up** -- Sequence / modal /
    bridge-arm gaps per EEEE drop list.

  * **Sami, Ship's Engineer** -- BEGINNING_OF_END_STEP +
    ``ConditionalOnTappedCreatures`` token-registration substrate
    blocked per QQQ / EEEE drop list.

  * **Optimistic Scavenger** -- bit-identical (event, effect-
    class) SHAPE to Drix Fatemaker (ENTERS +
    ``PutPlusOneCounterOnTargetCreature(1)``); no NEW shape
    coverage.  Honest exhaustion.

  * **Weapons Manufacturing** -- nested-trigger-on-token-printing
    shape (LEAVES_BATTLEFIELD trigger on the spawned Munitions
    token); deferred per YYY :206-210.

  * **Irreverent Gremlin** -- ``IfYouDo(MayDo(DiscardSelf),
    DrawCards(1))`` wrapper substrate + agent-picker requirement;
    deferred per EEEE Sunstar Lightsmith Sequence-wrapper
    rationale.

  * **Dawnsire, Sunstar Dreadnought** (Artifact YOU_ATTACK +
    ``DealDamageToTargetCreature(amount=100, optional=True)``):
    bridge gap -- ``deal_damage_to_target_creature`` is not a
    bridge arm kind (verified: ``_ta_dict_to_python_effect``
    raises UnknownEffectKindError).  The ``deal_damage`` arm
    exists but bridges to a different Effect class
    (``DealDamage``).  Honest exhaustion at the bridge-arm layer.

  * **Activated-ability cards** (Steelswarm Operator, Slagdrill
    Scrapper, Ripchain Razorkin, Kavaron Turbodrone, Gene
    Pollinator, Rust Harvester, The Dominion Bracelet, Requiem
    Monolith, Crystal Quarry, Dust Bowl, Eldrazi Temple, Sunken
    Citadel, Plaza of Heroes, Inkmoth Nexus, Mutavault, Magus of
    the Moon, etc.): AA-only activation or static-only; the AA +
    cost substrate is its own surface beyond the bare triggered-
    effect bridge.  Deferred -- same YYY drop discipline at
    :193-204.

  * **Subsystem-gated remainder** -- the long tail of Aura
    attachment full surface / Equipment activated-ability surface
    / Room / non-Effect gate cards / Land activated abilities /
    non-basic land substrate / Roving Actuator XXX-substrate; the
    EEEE-idiom does not unblock them.

  * **All previously-PROBED cards** with the same effect classes --
    Banishing Light, Sheltered by Ghosts (ZZZ), Stay Hidden / Stay
    Silent (ZZZ), Hardlight Containment, Diplomatic Relations
    (YYY), Astelli Reclaimer (YYY), Cryoshatter / Meltstrider's
    Gear (AAAA), Withering Torment (BBBB), Lightless Evangel /
    Skystinger (CCCC), Starwinder / Broodguard Elite (EEEE),
    Meltstrider Eulogist / Balemurk Leech (DDDD) -- already PROBED
    via earlier modules; not re-probed here.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
One card moves from ``covered_by_construction`` to the ``PROBED``
tier upon merge.  Prior PROBED count (with AAAA + BBBB + CCCC +
EEEE + DDDD wired in via PROBE_MODULES, post-DDDD landing -- main
HEAD ``751f0204`` post the Aura STEP 7 merge): 228.  Net delta from
this module: +1 (PROBED), -1 (covered).  Honest-exhaustion is the
dominant signal -- the covered_by_construction tier's remaining
members (post Meltstrider Eulogist + Balemurk Leech + Starwinder +
Broodguard Elite landing) are overwhelmingly blocked at the bridge-
arm / subsystem layer (token-registration, modal, Sequence-wrapper,
granted_keywords-rider, Equipment/Aura/Room substrate, AA-cost
substrate, IS_CAST stack-resolution divergence for the magecraft
family, non-basic land substrate) rather than new (event, effect-
class) shape coverage.
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
# Probe 1 -- Illvoi Operative: Creature IS_CAST triggered ->
#   PutPlusOneCounterOnSelf(amount=1).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Illvoi Operative")``
#      returns the parsed CardPrinting (Creature, Bird Soldier).
#   2. The IS_CAST triggered ability's effect is a
#      ``PutPlusOneCounterOnSelf`` instance with ``amount=1``.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``PutPlusOneCounterOnSelf(amount=1)`` instance.
#   4. Distinctness from sibling Effect classes is preserved (regression
#      guard against counter-effect-class collapse).
#   5. Python's ``resolve`` path drives the
#      ``state.resolving_source.plus_one_counters`` ->
#      ``add_plus_one_counters(source, amount)`` pipeline: with the
#      source carrying 0 counters pre-resolve, the source's counter
#      pool grows to 1 post-resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_illvoi_operative_parity():
    """**GENUINE real-EoE cross-engine probe -- Illvoi Operative
    (round 32 FFFF relaunch, Creature IS_CAST ->
    PutPlusOneCounterOnSelf(amount=1)).**

    Drives the **real parsed Illvoi Operative printing** through the
    Python-side ``PutPlusOneCounterOnSelf`` resolve path, validating
    the ``state.resolving_source`` -> ``add_plus_one_counters``
    pipeline on a controlled state (source gains 1 +1/+1 counter
    post-resolve).  Pairs the parse + bridge round-trip verification
    with the live Python resolve smoke, the same parse + bridge-
    round-trip + Python-side resolve idiom DDD slice 17 + YYY + ZZZ
    + AAAA + CCCC + EEEE + DDDD established.

    **NEW shape coverage:** the FIRST IS_CAST-event carrier of the
    ``PutPlusOneCounterOnSelf(amount=1)`` effect to land a
    PROBE_MODULES-credited ``_parity`` probe.  Complements:
      * Dockworker Drone (PROBED, ENTERS-event;
        ``tests/test_probe_covered_unprobed_a.py``:272 -- same
        effect class, ENTERS-event variant).
      * Seedship Agrarian (PROBED, ENTERS-event -- same effect
        class).
      * Lightless Evangel (PROBED via CCCC, IS_SACRIFICED-event --
        same effect class).
      * Insatiable Skittermaw / Kavaron Skywarden / Interceptor
        Mechan (PROBED via ZZ, BEGINNING_OF_END_STEP-event -- same
        effect class).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the **trigger event** (IS_CAST, a spell-cast
    stack-push event distinct from every other PROBED
    ``PutPlusOneCounterOnSelf`` consumer's resolve-time event
    firing).

    **Bridge arm exercised:**
    ``put_plus_one_counter_on_self`` (round-21+ closed-vocab effect
    arm in ``cross_engine.py``'s ``_ta_dict_to_python_effect``
    dispatch).

    **Setup (Python-side):**
      * p0 has Illvoi Operative on the battlefield (the Creature
        serving as ``resolving_source``).  ``plus_one_counters=0``
        pre-resolve.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "put_plus_one_counter_on_self", "amount": 1}``
        translates to a ``PutPlusOneCounterOnSelf(amount=1)``
        instance.
      * The Creature's IS_CAST triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: source's ``plus_one_counters`` grew to 1
        (the canonical ``add_plus_one_counters(state, source, 1)``
        mutation); the state log carries the
        ``"gets a +1/+1 counter"`` line.

    **YYY / SSS / UUU IS_CAST stack-resolution-divergence bypass:**
    Earlier drop notes deferred Illvoi Operative on cross-engine
    ``compare_fields`` grounds (the slice-12 ``test_mmm_probe_*``
    precedent documented an IS_CAST stack-resolution-order
    divergence that breaks full byte-equal probes on this trigger
    event).  The EEEE-idiom (parse + bridge round-trip + Python-
    side resolve, NO cross-engine ``compare_fields``) sidesteps
    that gap entirely: this probe verifies the Effect+bridge byte-
    equality and the Python-side resolve mutation, both of which
    are independent of the IS_CAST cross-engine stack-resolution
    path.  The harness-driven full-trajectory IS_CAST +
    SpellsCastThisTurn(n=2) magecraft-style trigger firing stays
    deferred -- this probe pins the Effect+bridge+resolve level
    only, the same bar the PROBED tier credits.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnSelf,
        MoveSelfCountersToTargetCreatureYouControl,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Illvoi Operative printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Illvoi Operative")
    )
    if real is None:
        pytest.skip("Illvoi Operative absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Illvoi Operative must be a Creature"
    )
    is_cast_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.IS_CAST
        ),
        None,
    )
    assert is_cast_ta is not None, (
        "Illvoi Operative must have an IS_CAST triggered ability "
        "(the trigger event distinguishing this probe from the more "
        "common ENTERS / IS_SACRIFICED / BEGINNING_OF_END_STEP "
        "consumers of PutPlusOneCounterOnSelf)"
    )
    assert isinstance(is_cast_ta.effect, PutPlusOneCounterOnSelf), (
        f"Illvoi Operative IS_CAST effect must be "
        f"PutPlusOneCounterOnSelf; got "
        f"{type(is_cast_ta.effect).__name__}"
    )
    assert is_cast_ta.effect.amount == 1, (
        f"Illvoi Operative PutPlusOneCounterOnSelf amount must be 1; "
        f"got {is_cast_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "put_plus_one_counter_on_self", "amount": 1}
    )
    assert isinstance(bridged, PutPlusOneCounterOnSelf), (
        f"Bridge arm 'put_plus_one_counter_on_self' must round-trip to "
        f"PutPlusOneCounterOnSelf; got {type(bridged).__name__}"
    )
    assert bridged.amount == 1, (
        f"Bridged PutPlusOneCounterOnSelf amount must be 1; "
        f"got {bridged.amount}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert is_cast_ta.effect == bridged, (
        f"Illvoi Operative IS_CAST effect must be byte-equal to the "
        f"bridged Effect; got parsed={is_cast_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(
        bridged, MoveSelfCountersToTargetCreatureYouControl,
    ), (
        "PutPlusOneCounterOnSelf must NOT collapse to "
        "MoveSelfCountersToTargetCreatureYouControl (EEEE Probe 2's "
        "counter-transfer effect that drains source counters to a "
        "target; PutPlusOneCounterOnSelf is a NET ADDITION of counters "
        "on source, not a transfer)."
    )
    assert not isinstance(bridged, DrawCards), (
        "PutPlusOneCounterOnSelf must NOT collapse to DrawCards "
        "(DDDD Probe 1's draw effect; different Effect class with "
        "different mutation semantics -- counter add vs. hand draw)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Illvoi Operative Creature on p0's battlefield.
    # ``plus_one_counters=0`` pre-resolve -- the resolve will increment
    # it to 1 via ``add_plus_one_counters(state, source, 1)``.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.plus_one_counters = 0
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)
    assert source.plus_one_counters == 0, (
        f"Pre-resolve sanity: source.plus_one_counters must start at "
        f"0; got {source.plus_one_counters}"
    )

    # ------------------------------------------------------------------
    # 5. Set resolving_source = the Illvoi Operative source object
    #    (per the PutPlusOneCounterOnSelf.resolve contract --
    #    counters.py:798 reads state.resolving_source as the counter
    #    recipient; the resolve aborts early with no-op if
    #    state.resolving_source is None).
    # ------------------------------------------------------------------
    py.resolving_source = source
    pre_log_len = len(py.log)

    # ------------------------------------------------------------------
    # 6. resolve: add 1 +1/+1 counter to source.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())
    py.resolving_source = None

    # Source's plus_one_counters incremented from 0 to 1.
    assert source.plus_one_counters == 1, (
        f"Illvoi Operative: source.plus_one_counters must equal 1 "
        f"post-resolve (PutPlusOneCounterOnSelf(amount=1) calls "
        f"add_plus_one_counters(state, source, 1)); got "
        f"source.plus_one_counters={source.plus_one_counters}"
    )
    # State log records the counter add.
    new_log = "\n".join(py.log[pre_log_len:])
    assert "gets a +1/+1 counter" in new_log, (
        f"State log must record the +1/+1 counter add; got new "
        f"log:\n{new_log}"
    )
    # Source remains on the battlefield (the resolve mutates the
    # source's counter field; it does NOT move the source).
    assert source in py.battlefield, (
        "Illvoi Operative: source must remain on the battlefield "
        "post-resolve (PutPlusOneCounterOnSelf is a counter-add "
        "mutation, not a zone change)"
    )

    # ------------------------------------------------------------------
    # 7. No-op short-circuit: resolve with state.resolving_source=None
    #    leaves the source's counter pool unchanged (the resolve's
    #    early-return at counters.py:798-800 when resolving_source is
    #    None).  This is the canonical "abort" path the effect
    #    documents -- a regression guard against silent fall-through.
    # ------------------------------------------------------------------
    py.resolving_source = None
    counters_before_noop = source.plus_one_counters
    log_before_noop = len(py.log)
    bridged.resolve(py, controller_id=0, targets=())
    assert source.plus_one_counters == counters_before_noop, (
        f"Illvoi Operative: with resolving_source=None, the resolve "
        f"must be a no-op; source.plus_one_counters must be unchanged "
        f"at {counters_before_noop}; got "
        f"{source.plus_one_counters}"
    )
    assert len(py.log) == log_before_noop, (
        f"Illvoi Operative: resolving_source=None no-op must NOT "
        f"append a log line (the resolve's early-return short-circuit "
        f"at counters.py:798-800); got log_len={len(py.log)} "
        f"(expected {log_before_noop})"
    )
