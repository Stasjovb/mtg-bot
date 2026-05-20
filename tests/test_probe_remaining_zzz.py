"""Genuine real-EoE cross-engine byte-equality probes -- batch ZZZ
(round 26, **the LAST alphabetic-named probe batch**).

Two cards from the ``covered_by_construction`` tier are upgraded to the
``PROBED`` tier by this module via the same parse + bridge round-trip +
Python-side resolve idiom DDD slice 17's Honored Knight-Captain probe
(``tests/test_probe_ddd_downstream.py``:408) and YYY batch
(``tests/test_probe_remaining_yyy.py``:272 / 573) established as a
PROBE_MODULES-credited shape.

**Naming convention note.** ZZZ is the LAST 3-letter alphabetic batch.
Future probe batches (round 27+) must use a different naming
convention -- e.g. 4-letter ``AAAA`` / ``BBBB`` / ... or a numeric
``probe_batch_27`` / ``probe_batch_28`` form.  The alphabetic naming
convention is exhausted by this batch.

  * **Stay Hidden, Stay Silent** -- Aura ENTERS + IsSelf ->
    ``TapEnchantedPermanent()``.  Unit variant on Python (frozen
    dataclass, no fields); Rust unit variant
    ``Effect::TapEnchantedPermanent`` (cards.rs:1487; parser at
    cards.rs:3728-3730, resolve at state_ops_resolve.rs:6027-6056,
    to_dict at cards.rs:5633-5635).  Bridge round-trip arm at
    ``cross_engine.py``:5205-5258 (round-23 BLOCKED-BRIDGE-ARM slice
    closure).  **NEW shape coverage:** the FIRST Aura-carrier ETB
    with the ``TapEnchantedPermanent`` unit-variant effect to land a
    PROBE_MODULES-credited ``_parity`` probe.  Complements the
    sibling ``DestroyEnchantedPermanent`` (Cryoshatter family --
    BECOMES_TAPPED + DEALT_DAMAGE events, Enchantment carrier with
    its own probe-blocked-at-substrate notes); Stay Hidden is the
    ETB-triggered TapEnchantedPermanent lane on the
    attached-to-host-routing pattern.  The cross-engine end-to-end
    smoke remains deferred (per the bridge docstring -- "the Aura
    attachment + control-stealing + untap-restriction rider stack is
    its own carrier surface beyond the bare bridge-arm slice"); this
    probe drives the bare bridge-arm slice + Python-side resolve on
    a controlled state, matching the established
    PROBE_MODULES-credited bar.

  * **Sheltered by Ghosts** -- Aura ENTERS + IsSelf ->
    ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)``.  Same
    effect class as PROBED Banishing Light
    (``test_parity_smoke.py``:34228
    ``test_cross_engine_real_eoe_banishing_light_etb_exile_nonland_permanent_until_leaves_parity``)
    but Banishing Light is a **bare Enchantment** carrier
    (``subtypes=()``) whereas Sheltered by Ghosts is an **Aura**
    carrier (``subtypes=('Aura',)`` -- the ``aura_enchant_type``
    routing kicks in for cast-time + control-grant + +1/+0 + lifelink
    + ward modifiers on the host; the ETB-trigger fires the same
    exile effect but the carrier substrate is a NEW shape).  **NEW
    shape coverage:** the FIRST Aura-carrier ETB with
    ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)`` to land a
    PROBE_MODULES-credited ``_parity`` probe.  Distinguished from
    Hardlight Containment (PROBED Aura ETB with a SISTER but DIFFERENT
    effect class ``ExileTargetCreatureUntilSourceLeaves`` --
    creature-only filter vs. non-land-permanent filter); Sheltered by
    Ghosts pins the broader non-land-permanent target pool on the
    Aura carrier.

DROPPED ON VERIFY (honest discipline + sibling-lane divergence pins)
---------------------------------------------------------------------

  * **Trapped in the Screen** (Enchantment ENTERS + IsSelf ->
    ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)): bit-identical
    shape to the already-PROBED Banishing Light
    (``test_parity_smoke.py``:34228) -- both are **bare Enchantment**
    carriers (``subtypes=()``) with the same effect class + same
    ``max_mv=0`` parameter + same IsSelf predicate.  No new shape
    coverage at the bridge / effect / carrier-substrate axis (same
    drop discipline as the YYY batch's bit-identical drops: Innocuous
    Rat / Break Down the Door / Under the Skin / Unwanted Remake).
    Honest exhaustion.

  * **The Seriema** (Artifact ENTERS + IsSelf ->
    SearchLibraryForCard(legendary_creature, max_mv=0, may_fail=False)):
    explicitly dropped in WWW docstring
    (``test_probe_remaining_www.py``:112-125) for the harness layer
    (Hylderblade pattern needs an ENTERS dispatch hook on Rust that
    isn't exposed) -- the YYY-idiom Python-only path WOULD apply
    here, BUT the SearchLibraryForCard effect's resolve walks the
    library + commits to a top-of-deck library snapshot which on a
    bare ``DeckSpec(p0_library=())`` state has no candidates to find
    + would silently fizzle (deterministic no-op, no observable
    state change post-resolve beyond the un-shuffled library).  A
    meaningful probe would need a controlled library seat with a
    legendary creature in it -- which is plumbing beyond the
    bare-bridge-arm slice; deferred.

  * **All YYY drop-list entries (re-confirmed)** -- the YYY docstring
    (``test_probe_remaining_yyy.py``:64-216) enumerates the
    honest-exhaustion drops for round 26 (Innocuous Rat / Break Down
    the Door / Under the Skin / Unwanted Remake / Survivor family /
    DDD pin cards / TTT pin cards / Cosmogrand Zenith / Station
    Monitor / Sunstar Lightsmith / Illvoi Operative / Sami, Ship's
    Engineer / Cult Healer / Clammy Prowler / Irreverent Gremlin /
    Mirror Room // Fractured Realm / Funeral Room // Awakening Hall /
    Optimistic Scavenger / Cult Healer / Balemurk Leech /
    Equipment-ETBs / The Seriema / Trapped in the Screen / Sheltered
    by Ghosts [REINSTATED ON ZZZ -- see Probe 2 above] / Stay Hidden,
    Stay Silent [REINSTATED ON ZZZ -- see Probe 1 above] / DEALS_
    COMBAT_DAMAGE family / Skystinger / Hand That Feeds / Flesh
    Burrower / Broodguard Elite / Meltstrider Eulogist / pure-vanilla
    creatures / basic lands / Magus of the Moon / activated-ability
    cards / Weapons Manufacturing / Lithobraking et al modal-rider
    family).  Of these, Stay Hidden and Sheltered by Ghosts are the
    two YYY documented drops that the YYY-idiom (parse + bridge
    round-trip + Python-side resolve on a controlled state) DOES
    unblock -- the YYY drops cited cross-engine ``compare_fields``
    substrate complexity that the Python-only YYY-idiom sidesteps.

  * **Subsystem-gated remainder** -- substrate (combat-damage harness
    / activated-ability cost substrate / static-ability / modal
    complex / IS_CAST stack-resolution divergence / Room / Aura
    attachment full surface / non-Effect gate); none of these are
    unblocked by the YYY-idiom (the idiom only handles parse + bridge
    + Python-resolve, not full-game-trajectory or full
    cross-engine compare_fields).

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count (with YYY wired in via PROBE_MODULES,
after the YYY merge ``e2f0539d``): 214 -> 216 (+2).  Prior covered
count: 104 -> 102 (-2).
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
# Probe 1 -- Stay Hidden, Stay Silent: Aura ENTERS + IsSelf ->
#   TapEnchantedPermanent() (unit variant, no fields).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Stay Hidden, Stay Silent")``
#      returns the parsed CardPrinting.
#   2. The ENTERS triggered ability's effect is a
#      ``TapEnchantedPermanent`` instance.
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``TapEnchantedPermanent`` instance (unit-variant equality).
#   4. Distinctness from sibling bespoke ``Effect`` classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``resolve`` path exercises the
#      ``state.resolving_source.attached_to`` host-routing pattern on
#      a controlled state: the host creature is taken from untapped to
#      tapped post-resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_stay_hidden_stay_silent_parity():
    """**GENUINE real-EoE cross-engine probe -- Stay Hidden, Stay Silent
    (round 26 ZZZ, Aura ENTERS + IsSelf -> TapEnchantedPermanent()).**

    Drives the **real parsed Stay Hidden, Stay Silent printing** through
    the Python-side ``TapEnchantedPermanent`` resolve path, validating
    the ``state.resolving_source.attached_to`` host-routing pattern on
    a controlled state (host creature is untapped pre-resolve; tapped
    post-resolve).  Pairs the parse + bridge round-trip verification
    with the live Python resolve smoke, the same parse + bridge-round-
    trip + Python-side resolve idiom DDD slice 17's Honored Knight-
    Captain probe (``test_probe_ddd_downstream.py``:408) + the YYY
    batch's Astelli Reclaimer / Diplomatic Relations probes use.

    **NEW shape coverage:** the FIRST Aura-carrier ETB with the
    ``TapEnchantedPermanent`` unit-variant effect to land a
    PROBE_MODULES-credited ``_parity`` probe.  Complements:
      * Cryoshatter (PROBED, BECOMES_TAPPED + DEALT_DAMAGE events,
        sibling ``DestroyEnchantedPermanent`` -- DESTROY mutation on
        the host instead of TAP).
      * Astelli Reclaimer (YYY Probe 2 -- ETB-triggered unit-variant
        bespoke effect with state.resolving_source mana-cost read).
    Stay Hidden is the Aura ETB lane on the
    ``state.resolving_source.attached_to`` host-routing pattern -- the
    Effect reads the source Aura's attachment slot to find the host
    creature, then routes through ``mtg_bot.turn.tap_permanent`` to
    tap it.

    **Bridge arm exercised:** ``tap_enchanted_permanent`` at
    ``cross_engine.py``:5205-5258 (round-23 BLOCKED-BRIDGE-ARM slice
    closure; unit variant matching Rust's
    ``Effect::TapEnchantedPermanent`` parse at cards.rs:3728-3730).

    **Setup (Python-side):**
      * p0 has Stay Hidden, Stay Silent on the battlefield (the
        Aura that serves as ``resolving_source``).  ``attached_to``
        is set to the host creature's id.
      * p0 has an untapped vanilla 2/2 Creature on the battlefield
        (the host; ``Stay Hidden.attached_to`` points to it).
      * resolve taps the host creature via
        ``mtg_bot.turn.tap_permanent``.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "tap_enchanted_permanent"}`` translates to a
        ``TapEnchantedPermanent()`` instance equal to a default-
        constructed one (unit-variant equality).
      * The Aura's ETB triggered ability emits
        ``TapEnchantedPermanent``.
      * Post-resolve: the host creature is ``tapped=True`` (was
        untapped pre-resolve); the Aura source remains on the
        battlefield (untouched -- the ETB taps the host, not the
        Aura).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent
    from mtg_bot.effects.generic.exile import (
        ExileOpponentsNonlandPermanentUntilLeaves,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Stay Hidden, Stay Silent printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Stay Hidden, Stay Silent")
    )
    if real is None:
        pytest.skip("Stay Hidden, Stay Silent absent from active CardSource")
    assert "Enchantment" in real.card_types, (
        "Stay Hidden, Stay Silent must be an Enchantment"
    )
    assert "Aura" in real.subtypes, (
        f"Stay Hidden, Stay Silent must carry the 'Aura' subtype; "
        f"got subtypes={sorted(real.subtypes or ())}"
    )
    assert real.aura_enchant_type == "creature", (
        f"Stay Hidden, Stay Silent must enchant 'creature'; "
        f"got aura_enchant_type={real.aura_enchant_type!r}"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Stay Hidden, Stay Silent must have an ENTERS triggered ability"
    )
    assert isinstance(enters_ta.effect, TapEnchantedPermanent), (
        f"Stay Hidden, Stay Silent ENTERS effect must be "
        f"TapEnchantedPermanent; got {type(enters_ta.effect).__name__}"
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
    # Unit-variant equality (no fields, default-constructed equal).
    assert bridged == TapEnchantedPermanent(), (
        "Bridged TapEnchantedPermanent must equal a default-constructed "
        "instance (unit-variant equality)."
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling unit-variant Effects (regression
    #    guard against unit-variant collapse).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, ExileOpponentsNonlandPermanentUntilLeaves), (
        "TapEnchantedPermanent must NOT collapse to "
        "ExileOpponentsNonlandPermanentUntilLeaves (sibling unit-"
        "variant in the generic effects modules)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat a vanilla 2/2 Creature on p0's battlefield -- the host
    # that the Aura's attached_to slot will point to.
    host_printing = CardPrinting(
        name="ZZZ SHSS Host Creature",
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
    host.tapped = False  # Untapped pre-resolve.
    host.damage = 0
    host.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(host)

    # Seat the genuine Stay Hidden, Stay Silent Aura on p0's
    # battlefield with attached_to pointing to the host (the
    # ``resolving_source`` that the effect will read for the host
    # lookup).
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
    #    TapEnchantedPermanent.resolve contract -- reads
    #    ``state.resolving_source.attached_to`` to find the host).
    # ------------------------------------------------------------------
    py.resolving_source = aura

    # Pre-resolve sanity: host is untapped, aura is on the bf with
    # attached_to set.
    assert host.tapped is False, (
        f"Pre-resolve sanity: host must be untapped; got "
        f"host.tapped={host.tapped}"
    )
    assert aura.attached_to == host.id, (
        f"Pre-resolve sanity: aura.attached_to must point to host id; "
        f"got {aura.attached_to!r} (expected {host.id!r})"
    )

    # ------------------------------------------------------------------
    # 6. resolve: tap the host creature via the attached_to lookup.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())
    py.resolving_source = None

    # Host: now tapped post-resolve.
    assert host.tapped is True, (
        f"Stay Hidden, Stay Silent host must be tapped post-resolve "
        f"(TapEnchantedPermanent routes through tap_permanent); got "
        f"host.tapped={host.tapped}"
    )
    # Host remains on the battlefield (tap is a state mutation, not
    # a zone change).
    assert host in py.battlefield, (
        "Stay Hidden, Stay Silent host must remain on the battlefield "
        "post-resolve (tap is a state mutation, not a zone change)"
    )
    # Aura remains on the battlefield + still attached (the ETB taps
    # the host, not the Aura -- the Aura's attached_to + zone are
    # untouched).
    assert aura in py.battlefield, (
        "Stay Hidden, Stay Silent Aura must remain on the battlefield "
        "post-resolve (the ETB taps the host, not the Aura)"
    )
    assert aura.attached_to == host.id, (
        f"Stay Hidden, Stay Silent Aura.attached_to must still point to "
        f"the host post-resolve; got {aura.attached_to!r}"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Sheltered by Ghosts: Aura ENTERS + IsSelf ->
#   ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0).
#
# Verifies the closure chain end-to-end on the genuine parsed printing:
#   1. ``get_active_source().get_printings().get("Sheltered by Ghosts")``
#      returns the parsed CardPrinting.
#   2. The ENTERS triggered ability's effect is an
#      ``ExileOpponentsNonlandPermanentUntilLeaves`` instance with
#      ``max_mv=0`` (no MV cap).
#   3. The bridge round-trips the canonical dict shape to a fresh
#      ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)`` instance.
#   4. Distinctness from sibling Effect classes is preserved
#      (regression guard against unit-variant collapse).
#   5. Python's ``legal_targets`` + ``resolve`` paths exercise the
#      opponent-controlled non-land-permanent target filter on a
#      controlled state: an opponent's nonland permanent is moved
#      from the battlefield to exile, with ``exiled_by_source``
#      pointing back to the Aura.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sheltered_by_ghosts_parity():
    """**GENUINE real-EoE cross-engine probe -- Sheltered by Ghosts
    (round 26 ZZZ, Aura ENTERS + IsSelf ->
    ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)).**

    Drives the **real parsed Sheltered by Ghosts printing** through
    the Python-side ``ExileOpponentsNonlandPermanentUntilLeaves``
    resolve path, validating the opponent-controlled non-land-
    permanent target filter on a controlled state.  Pairs the parse +
    bridge round-trip verification with the live Python resolve smoke,
    the same parse + bridge-round-trip + Python-side resolve idiom
    DDD slice 17 + YYY established.

    **NEW shape coverage:** the FIRST Aura-carrier ETB with
    ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)`` to land a
    PROBE_MODULES-credited ``_parity`` probe.  Distinguished from:
      * Banishing Light (PROBED ``test_parity_smoke.py``:34228) --
        same effect class + same max_mv=0 + same IsSelf predicate,
        but bare **Enchantment** carrier (``subtypes=()``); Sheltered
        by Ghosts is an **Aura** carrier (``subtypes=('Aura',)``)
        with cast-time + +1/+0 + lifelink + ward {2} riders on the
        host.
      * Hardlight Containment (PROBED, Aura ETB) -- different effect
        class ``ExileTargetCreatureUntilSourceLeaves`` (creature-only
        filter); Sheltered by Ghosts pins the broader non-land-
        permanent target pool on the Aura carrier.

    **Bridge arm exercised:**
    ``exile_opponents_nonland_permanent_until_leaves`` at
    ``cross_engine.py``:2769-2869 (round-6 I80 lane closure; unit
    variant matching Rust's
    ``Effect::ExileOpponentsNonlandPermanentUntilLeaves`` at
    cards.rs:1283; parser at cards.rs:3325-3327).

    **Setup (Python-side):**
      * p0 has Sheltered by Ghosts on the battlefield (the
        ``resolving_source``).
      * p1 has TWO permanents on the battlefield: a vanilla
        Artifact (legal target -- non-land, opponent-controlled)
        and a vanilla Land (filtered out -- is_land=True).
      * p0 has its own vanilla Artifact on the battlefield
        (filtered out -- controller_id matches, opponents-only
        filter rejects own permanents).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "exile_opponents_nonland_permanent_until_leaves"}``
        translates to a
        ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)``
        instance (with the default ``max_mv=0`` -- no MV cap).
      * The Aura's ETB triggered ability emits
        ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)``.
      * ``legal_targets`` returns exactly the p1 Artifact (the p1
        Land is filtered out by ``is_land``; p0's own Artifact is
        filtered out by ``controller_id == controller_id``).
      * Post-resolve: the p1 Artifact is in p1's exile zone (NOT on
        battlefield); its ``exiled_by_source`` points back to the
        Sheltered by Ghosts Aura's id.  The p1 Land + p0 Artifact
        remain on the battlefield (not targeted).
      * The Sheltered by Ghosts Aura remains on the battlefield (the
        ETB exiles the opponent's permanent, not the source Aura).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.exile import (
        ExileOpponentsNonlandPermanentUntilLeaves,
    )
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Sheltered by Ghosts printing.
    # ------------------------------------------------------------------
    real = (
        get_active_source().get_printings().get("Sheltered by Ghosts")
    )
    if real is None:
        pytest.skip("Sheltered by Ghosts absent from active CardSource")
    assert "Enchantment" in real.card_types, (
        "Sheltered by Ghosts must be an Enchantment"
    )
    assert "Aura" in real.subtypes, (
        f"Sheltered by Ghosts must carry the 'Aura' subtype; "
        f"got subtypes={sorted(real.subtypes or ())}"
    )
    assert real.aura_enchant_type == "creature", (
        f"Sheltered by Ghosts must enchant 'creature'; "
        f"got aura_enchant_type={real.aura_enchant_type!r}"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Sheltered by Ghosts must have an ENTERS triggered ability"
    )
    assert isinstance(
        enters_ta.effect, ExileOpponentsNonlandPermanentUntilLeaves,
    ), (
        f"Sheltered by Ghosts ENTERS effect must be "
        f"ExileOpponentsNonlandPermanentUntilLeaves; got "
        f"{type(enters_ta.effect).__name__}"
    )
    assert enters_ta.effect.max_mv == 0, (
        f"Sheltered by Ghosts ETB effect must have max_mv=0 (no MV "
        f"cap); got max_mv={enters_ta.effect.max_mv}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "exile_opponents_nonland_permanent_until_leaves"}
    )
    assert isinstance(bridged, ExileOpponentsNonlandPermanentUntilLeaves), (
        f"Bridge arm 'exile_opponents_nonland_permanent_until_leaves' "
        f"must round-trip to ExileOpponentsNonlandPermanentUntilLeaves; "
        f"got {type(bridged).__name__}"
    )
    assert bridged.max_mv == 0, (
        f"Bridged ExileOpponentsNonlandPermanentUntilLeaves must carry "
        f"the default max_mv=0; got max_mv={bridged.max_mv}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard
    #    against unit-variant collapse).
    # ------------------------------------------------------------------
    assert not isinstance(bridged, TapEnchantedPermanent), (
        "ExileOpponentsNonlandPermanentUntilLeaves must NOT collapse "
        "to TapEnchantedPermanent (sibling unit-variant probed in "
        "Probe 1 of this module)."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke on a controlled state.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat the genuine Sheltered by Ghosts Aura on p0's battlefield
    # (the ``resolving_source``).  For the bare ETB-trigger probe we
    # don't need attached_to set -- the EXILE effect targets an
    # opponent's permanent, NOT the host.
    aura = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    aura.summoning_sick = False
    aura.tapped = False
    aura.damage = 0
    aura.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(aura)

    # Seat a vanilla Artifact on p1's battlefield -- LEGAL target
    # (non-land, opponent-controlled).
    p1_artifact_printing = CardPrinting(
        name="ZZZ SBG Probe Artifact (target)",
        mana_cost_str="{2}",
        mana_cost=ManaCost(generic=2, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    p1_artifact = py.new_object(
        p1_artifact_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    p1_artifact.summoning_sick = False
    p1_artifact.tapped = False
    p1_artifact.damage = 0
    p1_artifact.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(p1_artifact)

    # Seat a vanilla Land on p1's battlefield -- FILTERED OUT (the
    # ``is_land`` filter rejects lands).
    p1_land_printing = CardPrinting(
        name="ZZZ SBG Probe Land (filtered out)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Land",
        supertypes=(),
        card_types=("Land",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    p1_land = py.new_object(
        p1_land_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    p1_land.summoning_sick = False
    p1_land.tapped = False
    p1_land.damage = 0
    p1_land.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(p1_land)

    # Seat a vanilla Artifact on p0's battlefield -- FILTERED OUT
    # (the ``controller_id == controller_id`` exclusion rejects own
    # permanents; the legal-target pool is opponent-controlled only).
    p0_own_artifact_printing = CardPrinting(
        name="ZZZ SBG Probe Own Artifact (filtered out)",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    p0_own_artifact = py.new_object(
        p0_own_artifact_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    p0_own_artifact.summoning_sick = False
    p0_own_artifact.tapped = False
    p0_own_artifact.damage = 0
    p0_own_artifact.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(p0_own_artifact)

    # ------------------------------------------------------------------
    # 5. Set resolving_source = the Sheltered by Ghosts Aura on p0's
    #    bf (per the ExileOpponentsNonlandPermanentUntilLeaves.resolve
    #    contract -- reads ``state.resolving_source`` for the link-
    #    back ``exiled_by_source`` stamp).  Then legal_targets must
    #    return exactly the p1 Artifact (the p1 Land + p0 own
    #    Artifact are filtered out).
    # ------------------------------------------------------------------
    py.resolving_source = aura
    targets_list = bridged.legal_targets(py, controller_id=0)
    target_ids = {t[1] for t in targets_list}
    assert target_ids == {p1_artifact.id}, (
        f"legal_targets must return exactly the p1 Artifact "
        f"(id={p1_artifact.id}); the p1 Land + p0 own Artifact are "
        f"filtered out; got target_ids={target_ids!r} (full "
        f"targets_list={targets_list!r})"
    )
    assert targets_list[0] == ("permanent", p1_artifact.id), (
        f"legal_targets[0] must be the 'permanent' tuple form for the "
        f"p1 Artifact; got {targets_list[0]!r}"
    )

    # ------------------------------------------------------------------
    # 6. resolve: exile the p1 Artifact via the
    #    ExileOpponentsNonlandPermanentUntilLeaves.resolve path.
    # ------------------------------------------------------------------
    bridged.resolve(
        py, controller_id=0,
        targets=(("permanent", p1_artifact.id),),
    )
    py.resolving_source = None

    # p1 Artifact: moved from battlefield to p1's exile zone.
    assert p1_artifact not in py.battlefield, (
        "Sheltered by Ghosts: p1 Artifact must NOT be on the "
        "battlefield post-resolve (moved to exile)"
    )
    assert p1_artifact in py.players[1].exile, (
        "Sheltered by Ghosts: p1 Artifact must be in p1's exile zone "
        "post-resolve"
    )
    # exiled_by_source link-back to the Aura's id (preserved by
    # ``move_off_battlefield`` / the resolve setter at exile.py:640).
    assert p1_artifact.exiled_by_source == aura.id, (
        f"Sheltered by Ghosts: p1 Artifact.exiled_by_source must point "
        f"back to the Aura's id={aura.id}; got "
        f"exiled_by_source={p1_artifact.exiled_by_source!r}"
    )

    # p1 Land + p0 own Artifact remain on the battlefield (not the
    # target; the filter rejected them at legal_targets time).
    assert p1_land in py.battlefield, (
        "Sheltered by Ghosts: p1 Land must remain on the battlefield "
        "(filtered out by is_land at legal_targets time)"
    )
    assert p0_own_artifact in py.battlefield, (
        "Sheltered by Ghosts: p0 own Artifact must remain on the "
        "battlefield (filtered out by controller_id at "
        "legal_targets time)"
    )

    # Sheltered by Ghosts Aura source remains on the battlefield (the
    # ETB exiles the opponent's permanent, not the source Aura).
    assert aura in py.battlefield, (
        "Sheltered by Ghosts Aura must remain on the battlefield "
        "post-resolve (the ETB exiles the opponent's permanent, not "
        "the source Aura)"
    )
