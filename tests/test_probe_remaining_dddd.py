"""Genuine real-EoE cross-engine byte-equality probes -- batch DDDD
(round 30, the FOURTH 4-letter probe batch -- post-ZZZ alphabetic-
exhaustion, sibling to in-flight EEEE).

The AAAA batch (``tests/test_probe_remaining_aaaa.py``:1-15) opened
the 4-letter naming convention post-ZZZ alphabetic exhaustion.  DDDD
is the fourth 4-letter batch (round 30); prior 4-letter batches are
AAAA (round 27), BBBB (round 28), CCCC (round 29 -- main HEAD
``bfa9829b``).  Subsequent batches follow ``EEEE`` / ``FFFF`` / ...
per the established 4-letter alphabetic cadence.

Two cards from the ``covered_by_construction`` tier are upgraded to
the ``PROBED`` tier by this module via the same parse + bridge round-
trip + Python-side resolve idiom DDD slice 17's Honored Knight-Captain
probe (``tests/test_probe_ddd_downstream.py``:408), the YYY batch's
two probes (``tests/test_probe_remaining_yyy.py``:272 / 573), the ZZZ
batch's two probes (``tests/test_probe_remaining_zzz.py``:173 / 413),
the AAAA batch's two probes (``tests/test_probe_remaining_aaaa.py``:231
/ 511), and the CCCC batch's two probes
(``tests/test_probe_remaining_cccc.py``:223 / 430) established as a
PROBE_MODULES-credited shape.

  * **Broodguard Elite** -- Creature with a LEAVES_BATTLEFIELD
    triggered ability emitting
    ``MoveSelfCountersToTargetCreatureYouControl()`` (unit variant,
    no fields).  Bridge arm at ``cross_engine.py``:5524 (round-25
    BLOCKED-BRIDGE-ARM slice closure; unit variant matching Rust's
    ``Effect::MoveSelfCountersToTargetCreatureYouControl`` parser at
    cards.rs:3686-3688).  **NEW shape coverage:** the FIRST
    PROBE_MODULES-credited ``_parity`` probe of the
    ``MoveSelfCountersToTargetCreatureYouControl`` effect class.
    Complements:
      * Dockworker Drone (already PROBED via
        ``tests/test_probe_covered_unprobed_a.py``:272 -- ETB-leg
        ``PutPlusOneCounterOnSelf(amount=1)``; the DIES leg
        ``MoveSelfCountersToTargetCreatureYouControl`` shape is
        sibling-covered-by-construction but unprobed at the
        ``_parity`` bar prior to this batch).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is **the effect class** -- this is the FIRST credited
    probe of ``MoveSelfCountersToTargetCreatureYouControl``, the
    counter-relocation primitive (distinct from ``+1/+1 counter
    add``-style ``PutPlusOneCounterOnSelf`` -- this primitive
    transfers existing counters off the source rather than adding
    new ones).  AND a new trigger event: LEAVES_BATTLEFIELD (a
    SUPERSET event of DIES that also fires on exile/bounce); the
    probe seats the counter-bearing source as the resolving_source
    and validates the transfer + zero-out smoke on a controlled
    state.

  * **Starwinder** -- Creature with a DEALS_COMBAT_DAMAGE triggered
    ability emitting ``DrawCardsEqualToResolvingCombatDamage()``
    (unit variant, no fields).  Bridge arm at
    ``cross_engine.py``:5696 (round-26 BLOCKED-BRIDGE-ARM slice
    closure; unit variant matching Rust's
    ``Effect::DrawCardsEqualToResolvingCombatDamage`` parser at
    cards.rs:4545-4551).  **NEW shape coverage:** the FIRST
    PROBE_MODULES-credited ``_parity`` probe of the
    ``DrawCardsEqualToResolvingCombatDamage`` effect class AND the
    FIRST DEALS_COMBAT_DAMAGE-event carrier ``_parity`` probe at all.
    Complements:
      * Anticausal Vestige, Dual-Sun Technique, Haliya Guided by
        Light, and 22 other EoE cards using the "deals combat damage
        to a player" combat-damage-trigger pattern with the "may draw
        that many cards" rider (per cross_engine.py:5735-5740 -- 25
        EoE oracle hits via scan; all covered-by-construction).
    The bridge arm + the Python-side resolve are the same; what's
    NEW here is **the effect class** -- this is the FIRST credited
    probe of ``DrawCardsEqualToResolvingCombatDamage``, the
    implicit-carrier-scalar draw primitive (distinct from
    ``DrawCards(count=...)`` -- this primitive reads
    ``state.resolving_combat_damage_amount`` at resolve time rather
    than carrying an explicit field).  AND a new trigger event:
    DEALS_COMBAT_DAMAGE (a combat-step event distinct from the
    BLOCKS / ATTACKS combat-step events the CCCC / earlier batches
    already pinned).

DROPPED ON VERIFY (honest discipline + sibling-lane divergence pins)
---------------------------------------------------------------------

  * **Clammy Prowler** (Creature ATTACKS + IsSelf ->
    GrantUnblockableUEOT(targets=..., attacking_only=True,
    exclude_self=True)): the ``GrantUnblockableUEOT`` effect requires
    target selection (the trigger picks another attacking creature),
    which means the probe shape requires either a controlled-state
    target seat + an agent picker, OR the bridge round-trip alone
    without resolve smoke (a strictly weaker shape than the parse +
    bridge + Python-resolve idiom DDD slice 17 / YYY / ZZZ / AAAA /
    CCCC established).  Honest exhaustion until the
    GrantUnblockableUEOT target-bearing probe-substrate lands (the
    bridge arm at cross_engine.py:6251-6285 ships the unit-variant
    bare form; the target-bearing rider is the deferred slice).

  * **Innocuous Rat** (Creature DIES + ``ManifestDread(count=1)``):
    re-confirmed honest exhaustion per the CCCC docstring
    (``test_probe_remaining_cccc.py``:126-138 -- ManifestDread
    resolve requires library substrate + choose_card_from_library
    agent + put_into_battlefield fan-out).  Deferred until the
    manifest-dread harness substrate is wired.

  * **Optimistic Scavenger** (Room-unlocked sibling trigger): the
    ROOM_FULLY_UNLOCKED event substrate requires a Room printing
    fully unlocked end-to-end; subsystem-gated per the CCCC
    drop-list (``test_probe_remaining_cccc.py``:119-124).

  * **Flesh Burrower / Hand That Feeds / Cult Healer**
    (``granted_keywords`` rider on ``PumpTargetCreatureUntilEOT`` /
    ``PumpSelfUntilEOT``): the bare bridge arm does NOT carry the
    rider per the CCCC / BBBB / YYY drop lists.  Re-confirmed honest
    exhaustion until a rider-bearing pump arm lands.

  * **Bottomless Pool // Locker Room / Funeral Room // Awakening
    Hall / Mirror Room // Fractured Realm / Surgical Suite //
    Hospital Room / Underwater Tunnel // Slimy Aquarium / Derelict
    Attic // Widow's Walk / Grand Entryway // Elegant Rotunda /
    Restricted Office // Lecture Hall / Moldering Gym // Weight
    Room / Ticket Booth // Tunnel of Hate**: Room subsystem +
    cascade ETB-fan-out makes the probe shape multi-axis;
    subsystem-gated per the BBBB drop-list
    (``test_probe_remaining_bbbb.py``:184-190).

  * **Let's Play a Game / Split Up** (Sorcery
    ``spell_effect=ModalChooseOne``): modal-choice substrate
    re-confirmed honest exhaustion per the CCCC docstring
    (``test_probe_remaining_cccc.py``:140-145).

  * **Vanish from Sight / Trapped in the Screen / Conductive
    Machete / Killer's Mask** (sibling-lane divergence pins or
    bit-identical shapes): re-confirmed honest exhaustion per the
    BBBB / CCCC / ZZZ docstrings.

  * **Lithobraking / Temporal Intervention / Under the Skin / Get
    Out / Weapons Manufacturing / Unwanted Remake / Unnerving
    Grasp / Cosmogrand Zenith / Patched Plaything / Magus of the
    Moon / pure-vanilla creatures / basic lands / Plaza of Heroes /
    Mana Confluence / Eldrazi Temple / non-basic land substrate
    cards**: re-confirmed honest exhaustion per the ZZZ + AAAA +
    BBBB + CCCC docstring drop-lists -- subsystem-gated, no NEW
    PROBE_MODULES-credited Effect-shape unlocked.

  * **All previously-PROBED cards** with the same effect classes --
    Banishing Light, Sheltered by Ghosts, Stay Hidden / Stay Silent,
    Cryoshatter, Meltstrider's Gear, Lightless Evangel, Skystinger,
    Withering Torment, etc. -- already PROBED via earlier modules;
    not re-probed here.

  * **Subsystem-gated remainder** -- the long tail of Aura
    attachment full surface / Equipment activated-ability surface /
    Room / IS_CAST stack-resolution / non-Effect gate cards; the
    YYY-idiom (parse + bridge + Python-resolve) does not unblock
    them.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED``
tier upon merge.  Prior PROBED count (with AAAA + BBBB + CCCC wired
in via PROBE_MODULES, post-CCCC landing -- main HEAD ``8fb691f3``):
224.  Net delta from this module: +2 (PROBED), -2 (covered).
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
# Probe 1 -- Broodguard Elite: Creature LEAVES_BATTLEFIELD triggered ->
#   MoveSelfCountersToTargetCreatureYouControl().
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Broodguard Elite")``
#      returns the parsed CardPrinting (Creature, Insect Knight).
#   2. The LEAVES_BATTLEFIELD triggered ability's effect is a
#      ``MoveSelfCountersToTargetCreatureYouControl`` instance with no
#      fields (unit variant) and predicate=IsSelf().
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``MoveSelfCountersToTargetCreatureYouControl()`` instance (unit-
#      variant equality with the default constructor).
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``resolve`` path drives the counter-relocation pipeline
#      on a controlled state: source has N=3 +1/+1 counters pre-resolve;
#      post-resolve the source has 0 and the target has +3 (from a base
#      of 0).  The state log records the move.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_broodguard_elite_parity():
    """**GENUINE real-EoE cross-engine probe -- Broodguard Elite
    (round 30 DDDD, Creature LEAVES_BATTLEFIELD ->
    MoveSelfCountersToTargetCreatureYouControl()).**

    Drives the **real parsed Broodguard Elite printing** through the
    Python-side ``MoveSelfCountersToTargetCreatureYouControl`` resolve
    path, validating the ``state.resolving_source.plus_one_counters``
    transfer pipeline on a controlled state (source has 3 counters pre-
    resolve; 0 post-resolve; target has +3 transferred).  Pairs the
    parse + bridge round-trip verification with the live Python resolve
    smoke, the same parse + bridge-round-trip + Python-side resolve
    idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC established.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited ``_parity``
    probe of the ``MoveSelfCountersToTargetCreatureYouControl`` effect
    class.  Complements:
      * Dockworker Drone (already PROBED via
        ``test_probe_covered_unprobed_a.py``:272 -- ETB-leg
        ``PutPlusOneCounterOnSelf(amount=1)``; the DIES sibling leg
        ``MoveSelfCountersToTargetCreatureYouControl`` is covered-by-
        construction but lacked a credited probe prior to this batch).
    The bridge arm + the Python-side resolve are the same; what's NEW
    here is the **effect class** (counter-relocation primitive: moves
    EXISTING counters off the source rather than ADDING new ones).
    AND a new trigger event: LEAVES_BATTLEFIELD (a SUPERSET event of
    DIES that also fires on exile/bounce; the probe drives the
    transfer + zero-out without firing the event itself -- the
    seat-and-resolve smoke parallels Cryoshatter's host-event probe).

    **Bridge arm exercised:** ``move_self_counters_to_target_creature_
    you_control`` at ``cross_engine.py``:5524 (round-25 BLOCKED-
    BRIDGE-ARM slice closure; unit variant matching Rust's
    ``Effect::MoveSelfCountersToTargetCreatureYouControl`` parser at
    cards.rs:3686-3688, to_dict at cards.rs:5591-5592, resolve at
    state_ops_resolve.rs reading
    ``state.resolving_source.plus_one_counters``).

    **Setup (Python-side):**
      * p0 has Broodguard Elite on the battlefield (the Creature
        serving as ``resolving_source``).  ``plus_one_counters=3``
        pre-resolve (seeded -- Broodguard's enters_with_counters_from_x
        is the natural source but the probe seeds directly to control
        the count).
      * p0 has a vanilla 2/2 Creature on the battlefield (the target;
        the only legal target slot since
        ``MoveSelfCountersToTargetCreatureYouControl.legal_targets``
        filters battlefield to controller-owned creatures and
        Broodguard Elite is the source).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "move_self_counters_to_target_creature_you_control"}``
        translates to a ``MoveSelfCountersToTargetCreatureYouControl()``
        instance equal to a default-constructed one (unit-variant
        equality).
      * The Creature's LEAVES_BATTLEFIELD triggered ability emits
        ``MoveSelfCountersToTargetCreatureYouControl()``.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: the source's ``plus_one_counters`` is 0 (was 3
        pre-resolve); the target's ``plus_one_counters`` is 3 (was 0
        pre-resolve); the state log records the counter-move line.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.effects.generic.counters import (
        MoveSelfCountersToTargetCreatureYouControl,
        PutPlusOneCounterOnSelf,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
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
    leaves_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.LEAVES_BATTLEFIELD
        ),
        None,
    )
    assert leaves_ta is not None, (
        "Broodguard Elite must have a LEAVES_BATTLEFIELD triggered "
        "ability (the SUPERSET-of-DIES event distinguishing this probe "
        "from the existing Dockworker-Drone DIES-leg sibling)"
    )
    assert isinstance(
        leaves_ta.effect, MoveSelfCountersToTargetCreatureYouControl,
    ), (
        f"Broodguard Elite LEAVES_BATTLEFIELD effect must be "
        f"MoveSelfCountersToTargetCreatureYouControl; got "
        f"{type(leaves_ta.effect).__name__}"
    )
    # IsSelf predicate -- the trigger fires when THIS creature leaves
    # the battlefield (not when another creature leaves).
    assert isinstance(leaves_ta.predicate, IsSelf), (
        f"Broodguard Elite LEAVES_BATTLEFIELD predicate must be IsSelf "
        f"(THIS creature's own leave); got "
        f"predicate={type(leaves_ta.predicate).__name__}"
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
    # Unit-variant equality with the default constructor.
    assert bridged == MoveSelfCountersToTargetCreatureYouControl(), (
        f"Bridged MoveSelfCountersToTargetCreatureYouControl must equal "
        f"a default-constructed instance (unit variant, no fields); got "
        f"bridged={bridged!r}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert leaves_ta.effect == bridged, (
        f"Broodguard Elite LEAVES_BATTLEFIELD effect must be byte-equal "
        f"to the bridged Effect; got parsed={leaves_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, PutPlusOneCounterOnSelf), (
        "MoveSelfCountersToTargetCreatureYouControl must NOT collapse "
        "to PutPlusOneCounterOnSelf (Dockworker Drone's ETB-leg sibling "
        "and CCCC Probe 1's Lightless Evangel emission; "
        "PutPlusOneCounterOnSelf ADDS a counter to the source, this "
        "primitive TRANSFERS existing counters off the source to a "
        "target -- distinct mutation semantics)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Broodguard Elite Creature on p0's battlefield
    # (the ``resolving_source``).  Seed plus_one_counters=3 directly
    # (the probe controls the count rather than firing Broodguard's
    # enters_with_counters_from_x trigger -- the probe pins the
    # transfer primitive, not the counter-seeding primitive).
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.plus_one_counters = 3
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Seat a vanilla target creature on p0's battlefield (the only
    # legal target -- legal_targets filters to controller-owned
    # creatures, and Broodguard itself is excluded as the source by
    # the typical trigger semantics).  Use a SYNTHETIC_CREATURE
    # vanilla 2/2 ("Stalwart Knight" is the established fixture per
    # test_move_self_counters_resolve.py).
    target_printing = SYNTHETIC_CREATURES["Stalwart Knight"]
    target = py.new_object(
        target_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    target.summoning_sick = False
    target.tapped = False
    target.damage = 0
    target.plus_one_counters = 0
    target.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(target)

    assert source.plus_one_counters == 3, (
        f"Pre-resolve sanity: source.plus_one_counters must start at 3 "
        f"(seeded); got {source.plus_one_counters}"
    )
    assert target.plus_one_counters == 0, (
        f"Pre-resolve sanity: target.plus_one_counters must start at 0; "
        f"got {target.plus_one_counters}"
    )

    # ------------------------------------------------------------------
    # 5. Set resolving_source = the Broodguard Elite source object on
    #    p0's bf (per the
    #    MoveSelfCountersToTargetCreatureYouControl.resolve contract --
    #    reads ``state.resolving_source.plus_one_counters`` for the
    #    transfer count).
    # ------------------------------------------------------------------
    py.resolving_source = source

    # ------------------------------------------------------------------
    # 6. resolve: transfer 3 +1/+1 counters from source to target.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=(("creature", target.id),))
    py.resolving_source = None

    # Source: counters zeroed.
    assert source.plus_one_counters == 0, (
        f"Broodguard Elite: source.plus_one_counters must equal 0 "
        f"post-resolve (MoveSelfCountersToTargetCreatureYouControl "
        f"clears the source's counters after transferring); got "
        f"source.plus_one_counters={source.plus_one_counters}"
    )
    # Target: counters incremented by the transferred amount (3).
    assert target.plus_one_counters == 3, (
        f"Broodguard Elite: target.plus_one_counters must equal 3 "
        f"post-resolve (3 +1/+1 counters transferred from source to "
        f"target via add_plus_one_counters); got "
        f"target.plus_one_counters={target.plus_one_counters}"
    )
    # State log records the counter-move.
    log_text = "\n".join(py.log)
    assert "3 +1/+1 counter(s) moved from" in log_text, (
        f"State log must record the +1/+1 counter transfer; got log:\n"
        f"{log_text}"
    )
    # Source remains on the battlefield (the resolve mutates the
    # counters fields; it does NOT move the source -- the LTB event
    # that fires this trigger is separate from the resolve's mutation).
    assert source in py.battlefield, (
        "Broodguard Elite: source must remain on the battlefield "
        "post-resolve (MoveSelfCountersToTargetCreatureYouControl is "
        "a counter-mutation, not a zone change)"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Starwinder: Creature DEALS_COMBAT_DAMAGE triggered ->
#   DrawCardsEqualToResolvingCombatDamage().
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Starwinder")``
#      returns the parsed CardPrinting (Creature, Leviathan).
#   2. The DEALS_COMBAT_DAMAGE triggered ability's effect is a
#      ``DrawCardsEqualToResolvingCombatDamage`` instance with no
#      fields (unit variant).
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``DrawCardsEqualToResolvingCombatDamage()`` instance (unit-
#      variant equality with the default constructor).
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``resolve`` path drives the
#      ``state.resolving_combat_damage_amount`` -> draw_n_cards pipeline
#      on a controlled state: amount=4 pre-resolve, library has 5 cards,
#      controller draws 4 cards post-resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_starwinder_parity():
    """**GENUINE real-EoE cross-engine probe -- Starwinder (round 30
    DDDD, Creature DEALS_COMBAT_DAMAGE ->
    DrawCardsEqualToResolvingCombatDamage()).**

    Drives the **real parsed Starwinder printing** through the
    Python-side ``DrawCardsEqualToResolvingCombatDamage`` resolve path,
    validating the ``state.resolving_combat_damage_amount`` ->
    ``draw_n_cards`` pipeline on a controlled state (carrier amount=4
    pre-resolve; controller draws 4 cards from a 5-card library
    post-resolve).  Pairs the parse + bridge round-trip verification
    with the live Python resolve smoke, the same parse + bridge-round-
    trip + Python-side resolve idiom DDD slice 17 + YYY + ZZZ + AAAA +
    CCCC established.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited ``_parity``
    probe of the ``DrawCardsEqualToResolvingCombatDamage`` effect class
    AND the FIRST DEALS_COMBAT_DAMAGE-event carrier ``_parity`` probe
    at all (the existing combat-step event carriers in PROBE_MODULES
    are ATTACKS / BLOCKS / DECLARED_AS_BLOCKED, not DEALS_COMBAT_DAMAGE).
    Complements:
      * Anticausal Vestige, Dual-Sun Technique, Haliya Guided by Light
        (and 22 other EoE consumers per cross_engine.py:5735-5740) --
        covered-by-construction but lacking a credited probe prior to
        this batch.
    The bridge arm + the Python-side resolve are the same; what's NEW
    here is **the effect class** (implicit-carrier-scalar draw
    primitive: reads ``state.resolving_combat_damage_amount`` at
    resolve time rather than carrying an explicit ``count`` field --
    distinct from ``DrawCards(count=N)`` which carries the count
    directly).  AND a new trigger event: DEALS_COMBAT_DAMAGE (a
    combat-step event distinct from BLOCKS / ATTACKS).

    **Bridge arm exercised:** ``draw_cards_equal_to_resolving_combat_
    damage`` at ``cross_engine.py``:5696 (round-26 BLOCKED-BRIDGE-ARM
    slice closure; unit variant matching Rust's
    ``Effect::DrawCardsEqualToResolvingCombatDamage`` parser at
    cards.rs:4545-4551, resolve reading
    ``state.resolving_combat_damage_amount``).

    **Setup (Python-side):**
      * p0 has Starwinder on the battlefield (the Creature serving as
        ``resolving_source``).
      * p0's library has 5 cards (vanilla synthetic creatures used as
        library fodder; the draw primitive doesn't care what cards
        are drawn -- only the count).
      * ``state.resolving_combat_damage_amount=4`` (the carrier scalar
        the combat-damage event handler would push before firing the
        trigger; the probe seeds it directly to control the count).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "draw_cards_equal_to_resolving_combat_damage"}``
        translates to a ``DrawCardsEqualToResolvingCombatDamage()``
        instance equal to a default-constructed one (unit-variant
        equality).
      * The Creature's DEALS_COMBAT_DAMAGE triggered ability emits
        ``DrawCardsEqualToResolvingCombatDamage()``.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's hand has 4 cards (drew 4 from a 5-card
        library); the library has 1 card left; the state log records
        the combat-damage-trigger draw line.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import BASIC_LANDS
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
    cd_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.DEALS_COMBAT_DAMAGE
        ),
        None,
    )
    assert cd_ta is not None, (
        "Starwinder must have a DEALS_COMBAT_DAMAGE triggered ability "
        "(the combat-step event distinguishing this probe from the "
        "existing ATTACKS / BLOCKS / ETB consumers in PROBE_MODULES)"
    )
    assert isinstance(
        cd_ta.effect, DrawCardsEqualToResolvingCombatDamage,
    ), (
        f"Starwinder DEALS_COMBAT_DAMAGE effect must be "
        f"DrawCardsEqualToResolvingCombatDamage; got "
        f"{type(cd_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards_equal_to_resolving_combat_damage"}
    )
    assert isinstance(bridged, DrawCardsEqualToResolvingCombatDamage), (
        f"Bridge arm 'draw_cards_equal_to_resolving_combat_damage' must "
        f"round-trip to DrawCardsEqualToResolvingCombatDamage; got "
        f"{type(bridged).__name__}"
    )
    # Unit-variant equality with the default constructor.
    assert bridged == DrawCardsEqualToResolvingCombatDamage(), (
        f"Bridged DrawCardsEqualToResolvingCombatDamage must equal a "
        f"default-constructed instance (unit variant, no fields); got "
        f"bridged={bridged!r}"
    )
    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    assert cd_ta.effect == bridged, (
        f"Starwinder DEALS_COMBAT_DAMAGE effect must be byte-equal to "
        f"the bridged Effect; got parsed={cd_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, MoveSelfCountersToTargetCreatureYouControl), (
        "DrawCardsEqualToResolvingCombatDamage must NOT collapse to "
        "MoveSelfCountersToTargetCreatureYouControl (Probe 1's sibling "
        "unit-variant effect with completely different semantics; the "
        "counter primitive transfers state-bearing counters between "
        "permanents, the draw primitive moves cards from library to "
        "hand -- distinct mutation surfaces)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Starwinder Creature on p0's battlefield (the
    # ``resolving_source``).  The resolve doesn't read attached_to or
    # plus_one_counters -- only state.resolving_combat_damage_amount
    # and the controller_id passed in.  Seating the source ensures the
    # state shape is consistent with a real combat-damage trigger
    # firing.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.damage = 0
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Stock p0's library with 5 cards (vanilla Plains -- the draw
    # primitive is library-content-agnostic, only the count matters).
    p0 = py.players[0]
    plains_printing = BASIC_LANDS["Plains"]
    for _ in range(5):
        lib_card = py.new_object(plains_printing, owner_id=0, zone=Zone.LIBRARY)
        p0.library.append(lib_card)

    # Sanity: p0's hand starts empty, library has 5.
    assert len(p0.hand) == 0, (
        f"Pre-resolve sanity: p0.hand must start empty; got "
        f"len(p0.hand)={len(p0.hand)}"
    )
    assert len(p0.library) == 5, (
        f"Pre-resolve sanity: p0.library must start with 5 cards; got "
        f"len(p0.library)={len(p0.library)}"
    )

    # ------------------------------------------------------------------
    # 5. Set the carrier scalar
    #    ``state.resolving_combat_damage_amount=4`` (the implicit "that
    #    many" the combat-damage event handler pushes before firing the
    #    trigger; per the resolve contract at
    #    effects/generic/draw_mill.py:100-112).
    # ------------------------------------------------------------------
    py.resolving_source = source
    py.resolving_combat_damage_amount = 4

    # ------------------------------------------------------------------
    # 6. resolve: draw 4 cards.
    # ------------------------------------------------------------------
    try:
        bridged.resolve(py, controller_id=0, targets=())
    finally:
        py.resolving_combat_damage_amount = 0
        py.resolving_source = None

    # Hand: 4 cards drawn.
    assert len(p0.hand) == 4, (
        f"Starwinder: p0.hand must have 4 cards post-resolve "
        f"(DrawCardsEqualToResolvingCombatDamage drew 4 = "
        f"resolving_combat_damage_amount); got len(p0.hand)={len(p0.hand)}"
    )
    # Library: 1 card left (5 - 4 drawn).
    assert len(p0.library) == 1, (
        f"Starwinder: p0.library must have 1 card left post-resolve "
        f"(5 - 4 drawn = 1); got len(p0.library)={len(p0.library)}"
    )
    # State log records the combat-damage-trigger draw.
    log_text = "\n".join(py.log)
    assert "combat-damage trigger" in log_text, (
        f"State log must record the combat-damage-trigger draw line; "
        f"got log:\n{log_text}"
    )
    assert "draws 4 cards" in log_text, (
        f"State log must record the 4-card draw count; got log:\n"
        f"{log_text}"
    )
    # Source remains on the battlefield (the resolve mutates p0's
    # hand + library; it does NOT move the source).
    assert source in py.battlefield, (
        "Starwinder: source must remain on the battlefield post-resolve "
        "(DrawCardsEqualToResolvingCombatDamage is a hand+library "
        "mutation, not a zone change for the source)"
    )
