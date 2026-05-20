"""Genuine real-EoE cross-engine byte-equality probes -- batch EEEE
(round 31 reclaim, the FIFTH 4-letter probe batch -- post-DDDD; this
slot was previously claimed by an agent that hit the API limit, that
branch is gone, slot reclaimed fresh).

The AAAA batch (``tests/test_probe_remaining_aaaa.py``) opened the
4-letter naming convention post-ZZZ alphabetic exhaustion.  EEEE is
the fifth 4-letter batch (round 31 reclaim); sibling lane DDDD
(round 30) is the fourth.  Subsequent batches follow ``FFFF`` /
``GGGG`` / ... per the established 4-letter alphabetic cadence.

Two cards from the ``covered_by_construction`` tier are upgraded to
the ``PROBED`` tier by this module via the same parse + bridge round-
trip + Python-side resolve idiom DDD slice 17's Honored Knight-Captain
probe (``tests/test_probe_ddd_downstream.py``:408), the YYY batch's
two probes (``tests/test_probe_remaining_yyy.py``:272 / 573), the ZZZ
batch's two probes (``tests/test_probe_remaining_zzz.py``:173 / 413),
the AAAA batch's two probes (``tests/test_probe_remaining_aaaa.py``:231
/ 511), and the CCCC batch's two probes (``tests/test_probe_remaining_
cccc.py``:223 / 430) established as a PROBE_MODULES-credited shape.

  * **Starwinder** -- Creature with a DEALS_COMBAT_DAMAGE triggered
    ability emitting ``DrawCardsEqualToResolvingCombatDamage()`` (the
    bare zero-arg unit-variant effect).  Bridge arm at
    ``cross_engine.py``: ``draw_cards_equal_to_resolving_combat_damage``
    (unit variant matching Rust's
    ``Effect::DrawCardsEqualToResolvingCombatDamage``).  **NEW shape
    coverage:** the FIRST DEALS_COMBAT_DAMAGE-event carrier of the
    ``DrawCardsEqualToResolvingCombatDamage`` effect to land a
    PROBE_MODULES-credited ``_parity`` probe.  Complements:
      * Fear of Failed Tests (covered_by_construction; same effect
        class but predicate is IsSelf+target-IsPlayer rather than
        Starwinder's And(Subject(IsCreature),Controlled,target-
        IsPlayer) -- both are DEALS_COMBAT_DAMAGE triggers but
        Starwinder's predicate fires on *any* creature you control,
        Fear of Failed Tests fires only on itself).
    The earlier WWW/YYY batches explicitly deferred this card with
    the rationale "end-to-end probe requires the cross-engine combat-
    damage harness (``resolve_combat_damage_python`` +
    ``deal_combat_damage_rust``) + the harness-side
    ``resolving_combat_damage_amount`` carrier-scalar push -- a
    distinctly richer setup than the spell-effect / end-step trigger
    probe shapes those batches shoot for"
    (``test_probe_remaining_www.py``:219-226;
    ``test_probe_remaining_yyy.py``:165-167).  THIS batch unblocks it
    by directly setting ``state.resolving_combat_damage_amount`` on
    the controlled state and calling the Python-side
    ``DrawCardsEqualToResolvingCombatDamage.resolve`` -- the same
    bare effect+bridge+resolve idiom established by DDD slice 17 /
    YYY / ZZZ / AAAA / CCCC.  The combat-damage harness is NOT
    required for the Effect+bridge+resolve byte-equality the probe
    asserts; what those earlier batches deferred was the full
    trajectory-driven combat-damage trigger fire, which is a
    distinct (stronger) test shape.  The harness-driven shape stays
    deferred -- this probe pins the Effect+bridge level only, the
    same bar the PROBED tier credits.

  * **Broodguard Elite** -- Creature with a LEAVES_BATTLEFIELD
    triggered ability emitting
    ``MoveSelfCountersToTargetCreatureYouControl()`` (the bare zero-
    arg unit-variant effect).  Bridge arm at ``cross_engine.py``:
    ``move_self_counters_to_target_creature_you_control`` (unit
    variant matching Rust's
    ``Effect::MoveSelfCountersToTargetCreatureYouControl``).
    **NEW shape coverage:** the FIRST LEAVES_BATTLEFIELD-event
    carrier of the ``MoveSelfCountersToTargetCreatureYouControl``
    effect to land a PROBE_MODULES-credited ``_parity`` probe.
    Complements:
      * Dockworker Drone (PROBED, ENTERS-event;
        ``test_parity_smoke.py``'s slug-credited
        ``test_cross_engine_real_eoe_dockworker_drone_*_parity`` --
        the existing pin for this effect class on a different
        trigger event).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the trigger **event** (LEAVES_BATTLEFIELD, a
    departure event, distinct from Dockworker Drone's ENTERS-event
    carrier) AND the carrier substrate (a plain Creature with the
    LTB trigger, no ETB substrate around it).  Broodguard Elite is
    the only EoE consumer of the LEAVES_BATTLEFIELD +
    ``MoveSelfCountersToTargetCreatureYouControl`` shape.

DROPPED ON VERIFY (honest discipline)
---------------------------------------------------------------------

  * **Fear of Failed Tests** (Enchantment Creature DEALS_COMBAT_DAMAGE
    + IsSelf -> ``DrawCardsEqualToResolvingCombatDamage()``):
    bit-identical effect-class shape to Starwinder (same Effect class,
    same trigger event, same bridge arm -- both bare zero-arg unit
    variants).  The predicate distinction (IsSelf+target-IsPlayer vs.
    Subject(IsCreature)+Controlled+target-IsPlayer) is metadata; the
    probe verifies the effect + the resolve-by-state-scalar mutation
    regardless of which predicate fires.  No NEW Effect+bridge axis
    coverage -- Starwinder already pins the Effect+bridge+resolve
    chain; Fear of Failed Tests would be a redundant probe per the
    same honest-exhaustion discipline CCCC used for Trapped in the
    Screen vs Banishing Light (``test_probe_remaining_cccc.py``:
    72-93).

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
    as SSS / QQQ / UUU / WWW / YYY.

  * **Equipment ETBs** (Conductive Machete / Cursed Windbreaker /
    Killer's Mask / Squire's Lightblade / Illvoi Light Jammer /
    Meltstrider's Gear): blocked by the SSS-round-23 ``put_into_
    battlefield`` non-creature ``summoning_sick=True`` divergence
    pin (``test_probe_remaining_sss.py``:107-148).  Honest
    exhaustion at the bridge-divergence layer.

  * **Hand That Feeds / Flesh Burrower / Skystinger-rider** (pump
    triggers carrying a ``granted_keywords`` rider): the
    ``pump_target_creature_until_eot`` / ``pump_self_until_eot``
    bridge arms drop the granted_keywords rider (same rider-omission
    gap CCCC enumerated at :96-109).  Honest exhaustion until a
    rider-bearing pump arm lands.

  * **Sami, Ship's Engineer** (BEGINNING_OF_END_STEP +
    ``ConditionalOnTappedCreatures(CreateToken(...))``): token-
    registration substrate + the BEGINNING_OF_END_STEP event require
    additional harness work beyond the bare effect+bridge slice --
    same deferral the WWW token-creation drop note covers.

  * **Sunstar Lightsmith** (IS_CAST +
    ``Sequence(PutPlusOneCounterOnSelf(1), DrawCards(1))``): the
    Sequence wrapper around two bridged effects raises the
    aggregation question -- the bare bridge dispatches per-effect,
    not on the Sequence container.  Deferred until a Sequence-level
    bridge slice lands (the YYY/ZZZ batches' Stay Hidden + Sheltered
    by Ghosts dropped a similar Sequence wrapper for the same
    reason).

  * **Temporal Intervention** (Sorcery
    ``spell_effect=TargetOpponentDiscardsCasterChoice``): no
    matching ``target_opponent_discards_caster_choice`` bridge arm in
    ``cross_engine.py`` (verified via direct
    ``_ta_dict_to_python_effect`` smoke -- raises
    ``unsupported effect kind`` UnknownEffectKindError).  Honest
    exhaustion at the bridge layer.

  * **Under the Skin / Innocuous Rat** (Sorcery / Creature DIES +
    ``ManifestDread``): the ManifestDread resolve substrate requires
    library + agent picker -- same deferral AAAA / CCCC dropped for
    Conductive Machete / Killer's Mask (Equipment ETB +
    ``ManifestDreadThenAttachSelf``) and Innocuous Rat.  Honest
    exhaustion until the manifest-dread harness substrate is wired.

  * **Let's Play a Game / Split Up** (Sorcery
    ``spell_effect=ModalChooseOne``): modal-choice substrate
    requires an agent picker + mode-resolution wiring (same drop
    as CCCC at :140-146).  Honest exhaustion at the modal-substrate
    layer.

  * **Subsystem-gated remainder** -- the long tail of Aura
    attachment full surface / Equipment activated-ability surface /
    Room / IS_CAST stack-resolution / non-Effect gate cards / Land
    activated abilities; the YYY-idiom (parse + bridge + Python-
    resolve) does not unblock them.

  * **All previously-PROBED cards** with the same effect classes --
    Banishing Light, Sheltered by Ghosts (ZZZ), Stay Hidden / Stay
    Silent (ZZZ), Hardlight Containment, Diplomatic Relations
    (YYY), Astelli Reclaimer (YYY), Cryoshatter / Meltstrider's
    Gear (AAAA), Withering Torment (BBBB), Lightless Evangel /
    Skystinger (CCCC) -- already PROBED via earlier modules; not
    re-probed here.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED``
tier upon merge.  Prior PROBED count (with AAAA + BBBB + CCCC wired
in via PROBE_MODULES, post-CCCC landing -- main HEAD ``8fb691f3``):
224.  Net delta from this module: +2 (PROBED), -2 (covered).  The
DDDD lane (round 30, in-flight as ``feature/probe-batch-dddd``) is
a sibling that may land first; the merge instructions pull
origin/main before pushing to absorb any DDDD-driven PROBE_MODULES
+ POOL_PARITY.md conflict, resolved by keeping both modules /
both card-name list entries.
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
# Probe 1 -- Starwinder: Creature DEALS_COMBAT_DAMAGE triggered ->
#   DrawCardsEqualToResolvingCombatDamage().
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Starwinder")``
#      returns the parsed CardPrinting (Creature, Leviathan).
#   2. The DEALS_COMBAT_DAMAGE triggered ability's effect is a
#      ``DrawCardsEqualToResolvingCombatDamage`` instance (bare unit
#      variant, no fields).
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``DrawCardsEqualToResolvingCombatDamage()`` instance.
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``resolve`` path drives the
#      ``state.resolving_combat_damage_amount`` -> ``draw_n_cards``
#      pipeline: with the carrier scalar set to N and the controller's
#      library carrying >=N cards, the controller's hand grows by N
#      post-resolve.  (The full combat-damage harness firing is NOT
#      probed here -- the carrier scalar is set directly, as the
#      effect's resolve contract documents at draw_mill.py:106; the
#      harness-driven shape is a stronger but distinct test that
#      WWW/YYY explicitly deferred.)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_starwinder_parity():
    """**GENUINE real-EoE cross-engine probe -- Starwinder (round 31
    EEEE reclaim, Creature DEALS_COMBAT_DAMAGE ->
    DrawCardsEqualToResolvingCombatDamage()).**

    Drives the **real parsed Starwinder printing** through the
    Python-side ``DrawCardsEqualToResolvingCombatDamage`` resolve path,
    validating the ``state.resolving_combat_damage_amount`` ->
    ``draw_n_cards`` pipeline on a controlled state (the controller's
    hand grows by the carrier amount post-resolve).  Pairs the parse +
    bridge round-trip verification with the live Python resolve smoke,
    the same parse + bridge-round-trip + Python-side resolve idiom DDD
    slice 17 + YYY + ZZZ + AAAA + CCCC established.

    **NEW shape coverage:** the FIRST DEALS_COMBAT_DAMAGE-event carrier
    of the ``DrawCardsEqualToResolvingCombatDamage`` effect to land a
    PROBE_MODULES-credited ``_parity`` probe.  Complements:
      * Fear of Failed Tests (covered_by_construction; same effect
        class on the same trigger event but predicate is IsSelf+target-
        IsPlayer rather than Starwinder's Subject(IsCreature)+
        Controlled+target-IsPlayer -- both bare zero-arg unit
        variants; Starwinder fires on *any* creature you control,
        Fear of Failed Tests fires only on itself).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the carrier (Starwinder, a plain Creature with the
    "any creature you control" predicate, the canonical consumer of
    this effect's broader-than-self trigger predicate).

    **Bridge arm exercised:**
    ``draw_cards_equal_to_resolving_combat_damage`` (unit variant
    matching Rust's
    ``Effect::DrawCardsEqualToResolvingCombatDamage``; bridge dispatch
    at ``cross_engine.py`` in the ``_ta_dict_to_python_effect``
    unit-variant section).

    **Setup (Python-side):**
      * p0 has Starwinder on the battlefield (the Creature serving
        as ``resolving_source``).
      * p0's library has N >= 3 cards (so the draw-3 has stock).
      * ``state.resolving_combat_damage_amount = 3`` (the carrier
        scalar set directly per the effect's resolve contract --
        draw_mill.py:106 documents that the resolve reads this
        scalar; the full combat-damage harness firing is NOT probed
        here, only the carrier-scalar -> draw chain at the
        Effect+bridge level the PROBED tier credits).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "draw_cards_equal_to_resolving_combat_damage"}``
        translates to a ``DrawCardsEqualToResolvingCombatDamage()``
        instance (bare, no fields).
      * The Creature's DEALS_COMBAT_DAMAGE triggered ability emits
        the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's hand grew by 3 cards (the carrier-amount);
        the state log carries the "draws 3 cards" line.
      * The carrier-amount=0 no-op short-circuit is also exercised
        (a second resolve with amount=0 leaves the hand unchanged
        and adds NO log line for that resolve).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsEqualToResolvingCombatDamage,
    )
    from mtg_bot.effects.generic.counters import (
        MoveSelfCountersToTargetCreatureYouControl,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Starwinder printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Starwinder")
    )
    if real is None:
        pytest.skip("Starwinder absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Starwinder must be a Creature"
    )
    dcd_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.DEALS_COMBAT_DAMAGE
        ),
        None,
    )
    assert dcd_ta is not None, (
        "Starwinder must have a DEALS_COMBAT_DAMAGE triggered ability "
        "(the trigger event distinguishing this probe from the more "
        "common ENTERS / ATTACKS-event consumers)"
    )
    assert isinstance(
        dcd_ta.effect, DrawCardsEqualToResolvingCombatDamage,
    ), (
        f"Starwinder DEALS_COMBAT_DAMAGE effect must be "
        f"DrawCardsEqualToResolvingCombatDamage; got "
        f"{type(dcd_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards_equal_to_resolving_combat_damage"}
    )
    assert isinstance(bridged, DrawCardsEqualToResolvingCombatDamage), (
        f"Bridge arm 'draw_cards_equal_to_resolving_combat_damage' "
        f"must round-trip to DrawCardsEqualToResolvingCombatDamage; "
        f"got {type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert dcd_ta.effect == bridged, (
        f"Starwinder DEALS_COMBAT_DAMAGE effect must be byte-equal "
        f"to the bridged Effect; got parsed={dcd_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(
        bridged, MoveSelfCountersToTargetCreatureYouControl,
    ), (
        "DrawCardsEqualToResolvingCombatDamage must NOT collapse to "
        "MoveSelfCountersToTargetCreatureYouControl (Probe 2's bare "
        "zero-arg unit-variant effect with different mutation "
        "semantics; draw reads state.resolving_combat_damage_amount, "
        "move reads state.resolving_source.plus_one_counters)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Starwinder Creature on p0's battlefield.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Stock p0's library with 3+ cards (so the draw-3 has stock).
    # Use Starwinder's own printing as a filler -- the printing
    # identity doesn't matter for the draw, only that the library
    # has N cards.  Match the existing seat-on-library pattern from
    # the YYY / ZZZ / AAAA / CCCC probes.
    p0 = py.players[0]
    initial_hand_size = len(p0.hand)
    for _ in range(5):
        filler = py.new_object(real, owner_id=0, zone=Zone.LIBRARY)
        p0.library.append(filler)
    initial_library_size = len(p0.library)
    assert initial_library_size >= 3, (
        f"Pre-resolve sanity: p0 library must have at least 3 cards "
        f"so the draw-3 has stock; got len={initial_library_size}"
    )

    # ------------------------------------------------------------------
    # 5. Set resolving_combat_damage_amount = 3 (the carrier scalar
    #    the effect's resolve contract reads -- draw_mill.py:106).
    # ------------------------------------------------------------------
    py.resolving_source = source
    py.resolving_combat_damage_amount = 3
    pre_log_len = len(py.log)

    # ------------------------------------------------------------------
    # 6. resolve: draw 3 cards.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    # p0's hand grew by 3.
    assert len(p0.hand) == initial_hand_size + 3, (
        f"Starwinder: p0 hand size must be initial+3 post-resolve "
        f"(DrawCardsEqualToResolvingCombatDamage with amount=3 calls "
        f"draw_n_cards(state, 0, 3)); got len={len(p0.hand)} "
        f"(expected {initial_hand_size + 3})"
    )
    # Library shrank by 3.
    assert len(p0.library) == initial_library_size - 3, (
        f"Starwinder: p0 library size must be initial-3 post-resolve; "
        f"got len={len(p0.library)} (expected "
        f"{initial_library_size - 3})"
    )
    # State log records the draw.
    new_log = "\n".join(py.log[pre_log_len:])
    assert "draws 3 cards (combat-damage trigger)" in new_log, (
        f"State log must record the combat-damage draw; got new "
        f"log:\n{new_log}"
    )

    # ------------------------------------------------------------------
    # 7. No-op short-circuit: resolve with amount=0 leaves hand
    #    unchanged and adds NO new log line (the resolve's amount<=0
    #    early-return at draw_mill.py:107).
    # ------------------------------------------------------------------
    py.resolving_combat_damage_amount = 0
    hand_before_zero = len(p0.hand)
    log_before_zero = len(py.log)
    bridged.resolve(py, controller_id=0, targets=())
    assert len(p0.hand) == hand_before_zero, (
        f"Starwinder: amount=0 must be a no-op; hand size must be "
        f"unchanged at {hand_before_zero}; got len={len(p0.hand)}"
    )
    assert len(py.log) == log_before_zero, (
        f"Starwinder: amount=0 no-op must NOT append a log line "
        f"(the resolve's early-return short-circuit at draw_mill.py:"
        f"107); got log_len={len(py.log)} (expected "
        f"{log_before_zero})"
    )

    py.resolving_source = None
    py.resolving_combat_damage_amount = 0

    # Source remains on the battlefield (the resolve mutates the
    # carrier-amount-driven draw; it does NOT move the source).
    assert source in py.battlefield, (
        "Starwinder: source must remain on the battlefield post-"
        "resolve (DrawCardsEqualToResolvingCombatDamage is a draw "
        "trigger, not a zone change)"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Broodguard Elite: Creature LEAVES_BATTLEFIELD triggered ->
#   MoveSelfCountersToTargetCreatureYouControl().
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Broodguard Elite")``
#      returns the parsed CardPrinting (Creature, Insect Knight).
#   2. The LEAVES_BATTLEFIELD triggered ability's effect is a
#      ``MoveSelfCountersToTargetCreatureYouControl`` instance (bare
#      unit variant, no fields).
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``MoveSelfCountersToTargetCreatureYouControl()`` instance.
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``resolve`` path drives the
#      ``state.resolving_source.plus_one_counters`` ->
#      ``add_plus_one_counters(target)`` pipeline: with the source
#      carrying N counters and a target creature on the battlefield,
#      the target gains N counters and the source's counter pool
#      drains to 0 post-resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_broodguard_elite_parity():
    """**GENUINE real-EoE cross-engine probe -- Broodguard Elite
    (round 31 EEEE reclaim, Creature LEAVES_BATTLEFIELD ->
    MoveSelfCountersToTargetCreatureYouControl()).**

    Drives the **real parsed Broodguard Elite printing** through the
    Python-side ``MoveSelfCountersToTargetCreatureYouControl`` resolve
    path, validating the ``state.resolving_source.plus_one_counters``
    -> ``add_plus_one_counters(target)`` pipeline on a controlled
    state (target gains the source's counter count; source counter
    pool drains to 0 post-resolve).  Pairs the parse + bridge round-
    trip verification with the live Python resolve smoke, the same
    parse + bridge-round-trip + Python-side resolve idiom DDD slice
    17 + YYY + ZZZ + AAAA + CCCC established.

    **NEW shape coverage:** the FIRST LEAVES_BATTLEFIELD-event carrier
    of the ``MoveSelfCountersToTargetCreatureYouControl`` effect to
    land a PROBE_MODULES-credited ``_parity`` probe.  Complements:
      * Dockworker Drone (PROBED via the slug-credited parity_smoke
        test; ENTERS-event carrier of the same effect class -- a
        different trigger event + carrier substrate).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is the trigger **event** (LEAVES_BATTLEFIELD, a
    departure event, distinct from Dockworker Drone's ENTERS-event
    carrier) and the carrier substrate (a plain Creature with the
    LTB trigger, no ETB substrate around it).

    **Bridge arm exercised:**
    ``move_self_counters_to_target_creature_you_control`` (unit
    variant matching Rust's
    ``Effect::MoveSelfCountersToTargetCreatureYouControl``; bridge
    dispatch at ``cross_engine.py`` in the
    ``_ta_dict_to_python_effect`` unit-variant section).

    **Setup (Python-side):**
      * p0 has Broodguard Elite on the battlefield (the Creature
        serving as ``resolving_source``).  ``plus_one_counters=2``
        pre-resolve (the carrier scalar -- the LTB trigger fires
        when the creature with counters leaves the battlefield, so
        the source's counter count is read off the still-existing
        ``state.resolving_source`` reference).
      * p0 also has a target creature on the battlefield with
        ``plus_one_counters=0`` (the "target creature you control"
        recipient).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "move_self_counters_to_target_creature_you_control"}``
        translates to a ``MoveSelfCountersToTargetCreatureYouControl()``
        instance (bare, no fields).
      * The Creature's LEAVES_BATTLEFIELD triggered ability emits the
        same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: target gained 2 counters (counters from
        source moved); source's counter pool is 0; the state log
        carries the "+1/+1 counter(s) moved" line.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.counters import (
        MoveSelfCountersToTargetCreatureYouControl,
    )
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsEqualToResolvingCombatDamage,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Broodguard Elite printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Broodguard Elite")
    )
    if real is None:
        pytest.skip("Broodguard Elite absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Broodguard Elite must be a Creature"
    )
    ltb_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.LEAVES_BATTLEFIELD
        ),
        None,
    )
    assert ltb_ta is not None, (
        "Broodguard Elite must have a LEAVES_BATTLEFIELD triggered "
        "ability (the trigger event distinguishing this probe from "
        "the existing ENTERS-event Dockworker Drone consumer of "
        "MoveSelfCountersToTargetCreatureYouControl)"
    )
    assert isinstance(
        ltb_ta.effect, MoveSelfCountersToTargetCreatureYouControl,
    ), (
        f"Broodguard Elite LEAVES_BATTLEFIELD effect must be "
        f"MoveSelfCountersToTargetCreatureYouControl; got "
        f"{type(ltb_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "move_self_counters_to_target_creature_you_control"}
    )
    assert isinstance(bridged, MoveSelfCountersToTargetCreatureYouControl), (
        f"Bridge arm 'move_self_counters_to_target_creature_you_control' "
        f"must round-trip to MoveSelfCountersToTargetCreatureYouControl; "
        f"got {type(bridged).__name__}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert ltb_ta.effect == bridged, (
        f"Broodguard Elite LEAVES_BATTLEFIELD effect must be byte-equal "
        f"to the bridged Effect; got parsed={ltb_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(
        bridged, DrawCardsEqualToResolvingCombatDamage,
    ), (
        "MoveSelfCountersToTargetCreatureYouControl must NOT collapse "
        "to DrawCardsEqualToResolvingCombatDamage (Probe 1's bare "
        "zero-arg unit-variant effect with different mutation "
        "semantics; move reads state.resolving_source.plus_one_"
        "counters and writes to target, draw reads "
        "state.resolving_combat_damage_amount and writes to hand)."
    )
    # requires_target distinguishes this effect from many other
    # bare-no-arg effects -- it asks for a specific target.
    assert bridged.requires_target() is True, (
        "MoveSelfCountersToTargetCreatureYouControl must require a "
        "target (its resolve dereferences targets[0])"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Broodguard Elite Creature on p0's battlefield
    # with 2 +1/+1 counters on it (the carrier scalar -- the LTB
    # trigger fires when this creature with counters leaves; resolve
    # reads state.resolving_source.plus_one_counters).
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.plus_one_counters = 2
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Seat a second p0 creature as the target.  Reuse Broodguard
    # Elite's printing for simplicity -- the target's printing
    # identity doesn't matter, only that it's a Creature with
    # controller_id=0 (per the legal_targets filter at counters.py:
    # 279-282).  plus_one_counters=0 pre-resolve.
    target = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    target.summoning_sick = False
    target.tapped = False
    target.damage = 0
    target.plus_one_counters = 0
    target.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(target)
    assert target.plus_one_counters == 0, (
        f"Pre-resolve sanity: target.plus_one_counters must start at "
        f"0; got {target.plus_one_counters}"
    )

    # ------------------------------------------------------------------
    # 5. Set resolving_source = the Broodguard Elite source object
    #    (per the MoveSelfCountersToTargetCreatureYouControl.resolve
    #    contract -- counters.py:288 reads state.resolving_source for
    #    the counter count, then drains source.plus_one_counters to
    #    0 post-mutation).
    # ------------------------------------------------------------------
    py.resolving_source = source
    pre_log_len = len(py.log)

    # ------------------------------------------------------------------
    # 6. resolve: move 2 counters from source to target.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=(("creature", target.id),))
    py.resolving_source = None

    # Target: plus_one_counters incremented from 0 to 2 (the count
    # moved from source).
    assert target.plus_one_counters == 2, (
        f"Broodguard Elite: target.plus_one_counters must equal 2 "
        f"post-resolve (the count moved from source via "
        f"add_plus_one_counters); got "
        f"target.plus_one_counters={target.plus_one_counters}"
    )
    # Source: counter pool drained to 0 (the move is non-replicating).
    assert source.plus_one_counters == 0, (
        f"Broodguard Elite: source.plus_one_counters must drain to 0 "
        f"post-resolve (the move is a transfer, not a duplicate); "
        f"got source.plus_one_counters={source.plus_one_counters}"
    )
    # State log records the move.
    new_log = "\n".join(py.log[pre_log_len:])
    assert "2 +1/+1 counter(s) moved" in new_log, (
        f"State log must record the +1/+1 counter move; got new "
        f"log:\n{new_log}"
    )
    # Both objects remain on the battlefield (the resolve mutates
    # counter fields; it does NOT move zones).
    assert source in py.battlefield, (
        "Broodguard Elite: source must remain on the battlefield "
        "post-resolve (MoveSelfCountersToTargetCreatureYouControl is "
        "a counter-transfer mutation; the LTB-trigger-firing in real "
        "play is a separate state transition the resolve does not "
        "model)"
    )
    assert target in py.battlefield, (
        "Broodguard Elite: target must remain on the battlefield "
        "post-resolve (counter-transfer is a layer-7 mutation, not "
        "a zone change)"
    )
