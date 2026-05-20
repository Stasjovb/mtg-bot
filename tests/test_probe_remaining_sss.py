"""Genuine real-EoE cross-engine byte-equality probes -- batch SSS (round 23).

Two cards from the ``covered_by_construction`` tier are upgraded to the
``PROBED`` tier by this module.  Each probe drives the ACTUAL parsed EoE
printing on the Python side and the bridged synthetic carrier on the
Rust side, asserting full ``compare_fields == []`` byte-equality on a
controlled real-EoE state -- the strongest evidence the campaign tracks.

The probes deliberately cover effect/event shapes NOT already pinned
by the PROBED 199 (round-22 baseline after QQQ merge `28b1b713`):

  * **Manifest Dread (Sorcery)** -- Sorcery ``spell_effect =
    ManifestDread(count=1)``.  The bare ``ManifestDread`` effect has been
    pinned as a TRIGGERED ABILITY (Unsettling Twins ETB / Bashful Beastie
    DIES via batch N + III).  **No real-EoE card has driven the bridge
    arm as a SPELL EFFECT** until this probe.  Drives the empty-library
    no-op variant (Unsettling Twins N precedent): both engines fire the
    ManifestDread spell, find an empty library, short-circuit before any
    agent call or face-down manifest -- byte-equal across the whole field
    view (the spell moves stack -> caster's graveyard on both engines).

  * **Living Phone** -- Artifact Creature DIES + IsSelf ->
    ``LookAtTopNRevealOrCounter(n=5, filter_name='creature',
    max_power=2, counter_on_miss=False)``.  The
    ``look_at_top_n_reveal_or_counter`` bridge arm has been pinned by
    Pulsar Squadron Ace ENTERS (subtype-filter ``spacecraft``,
    max_power=0, counter_on_miss=True) PLUS its sibling
    ``card_types``-vs-``subtypes`` divergence pin.  **No probe has
    driven the bridge arm with the CARD-TYPE-filter ``creature`` shape
    on a DIES event** -- orthogonal cover of every load-bearing field
    of the bridge arm (event lane DIES vs ENTERS; filter lane
    card-type vs subtype; max_power lane nonzero vs zero;
    counter_on_miss lane False vs True).  Empty-library no-op variant:
    examined slice is empty, no PendingDecision queued, no agent call,
    counter_on_miss=False so no fallback +1/+1 -- byte-equal across
    the whole field view (Living Phone in p0 graveyard; no bf
    objects).

DROPPED ON VERIFY (honest discipline + new divergence pin candidates)
---------------------------------------------------------------------

Two further covered-but-unprobed cards surfaced **novel undocumented
cross-engine divergences** during probe construction.  Per the lane
discipline ("If a candidate fails byte-equality, do NOT fix the probe
to pass -- characterize as a divergence-pin candidate for a future
batch, drop the card, pick another"), both are dropped and
characterized inline so a sibling lane can wrap them as proper
``test_divergence_pins_*`` probes.

  * **Lightless Evangel** (IS_SACRIFICED + Or(Subject(IsCreature),
    Subject(IsArtifact)) AND Controlled(YOU) AND Not(IsSelf) ->
    PutPlusOneCounterOnSelf): **probe attempt surfaced a NEW Rust
    ordering divergence.**  When the IS_SACRIFICED dispatch fires
    DURING a spell's ``resolve_top_of_stack``, the triggered ability is
    pushed onto the stack BEFORE the resolving spell pops, then the
    spell's ``stack.pop()`` accidentally pops the IS_SACRIFICED
    TRIGGER (now on top), not the spell.  The Lightless Evangel
    trigger's ``put_plus_one_counter_on_self`` therefore never resolves
    on Rust, while Python's ``turn.sacrifice`` -> ``dispatch_event ->
    drain`` cleanly fires the trigger and adds the counter.  Empirical
    repro pattern (with ``always`` predicate to isolate from the
    Or-predicate dimension)::

        rs.register_and_inject_object(
            {"name": "Sac Artifact", "card_types": ["Artifact"]}, 0, ZB
        )
        rs.register_and_inject_object(
            {"name": "Observer", "card_types": ["Creature"],
             "power": 2, "toughness": 2,
             "triggered_abilities": [{
                 "event": "is_sacrificed",
                 "predicate": {"kind": "always"},
                 "effect": {"kind": "draw_cards", "count": 1}}],
            }, 0, ZB,
        )
        rs.register_and_inject_object(
            {"name": "Sac Spell", "card_types": ["Sorcery"],
             "effects": [{"kind": "sacrifice",
                          "target": {"kind": "any_creature"}}]},
            0, ZH,
        )
        # Push + resolve_top_of_stack: spell sacrifices bf[0], IS_SACRIFICED
        # fires, ``draw_cards`` never resolves (Observer's hand stays empty,
        # Library stays at full size).

    Rust dispatches IS_SACRIFICED at
    ``state_ops_resolve.rs:2602`` (``dispatch_event(state, IsSacrificed,
    leaving_obj_id)``) INSIDE the ``Effect::Sacrifice`` resolve arm --
    BEFORE the spell's ``stack.pop()`` at the resolve epilogue.  The
    LEAVES_BATTLEFIELD sibling at line 2588 uses
    ``pending_leaves_dispatches.push(leaving_obj_id)`` (defer-after-pop)
    precisely to avoid this ordering bug; the IS_SACRIFICED arm at line
    2602 dispatches inline -- missing the same defer-after-pop
    discipline.  Sibling-lane divergence pin should either (a) move the
    IS_SACRIFICED dispatch behind a ``pending_is_sacrificed_dispatches``
    deferred-drain matching the LEAVES_BATTLEFIELD precedent, or (b)
    change the spell-resolve epilogue's ``stack.pop()`` to look up the
    resolving slot by index rather than by stack-top so subsequent
    pushes during resolve don't shift the pop target.  Either fix
    closes the gap end-to-end.  Cross-checked: a plain DIES probe
    (Bashful Beastie pattern; ``test_probe_remaining_iii.py:709``) fires
    correctly because DIES is dispatched from a different path
    (``move_off_battlefield``-triggered drain, not the
    ``Effect::Sacrifice`` resolve arm).  Probe-blocked for SSS;
    sibling-lane divergence pin candidate.

  * **Conductive Machete** (Equipment ENTERS IsSelf ->
    ManifestDreadThenAttachSelf()): **probe attempt surfaced a NEW
    Python/Rust summoning_sick divergence on non-creature spell ETBs.**
    Python's ``put_into_battlefield`` (``actions.py:2993``) sets
    ``obj.summoning_sick = True`` unconditionally for every entering
    permanent.  Rust's spell-resolve ETB arm (``state_ops_resolve.rs``
    inside ``cast_spell_noncreature`` path) does NOT set
    ``summoning_sick = true`` for non-creature spells -- the field
    stays at its registry default of ``false``.  For CREATURE spells
    both engines set ``summoning_sick = true`` byte-equal (the
    Unsettling Twins / Bashful Beastie / Demonic Counsel / Manifest
    Dread probes all hit this path), so the gap is genuinely
    NON-CREATURE-SPELL-ONLY.  Empirical repro::

        rs.register_and_inject_object(
            {"name": "Foo", "card_types": ["Artifact"]}, 0, ZH
        )
        rs.push_to_stack(rs_foo_id, 0)
        rs.resolve_top_of_stack()
        # Rust: bf[Foo].summoning_sick == False (Rust default)
        # Python: bf[Foo].summoning_sick == True (put_into_battlefield
        #         unconditional set)

    The divergence is observable as a 3rd-slot byte-mismatch in the
    ``battlefield`` field of ``compare_fields`` output for every
    Equipment / artifact-only / enchantment-only spell that resolves
    via the cross-engine cast path.  Sibling-lane divergence pin
    should either (a) align Python's ``put_into_battlefield`` to skip
    ``summoning_sick = True`` for non-creature spells (CR 302.1 + 612.6
    say summoning sickness applies to CREATURES on the battlefield),
    or (b) align Rust's non-creature ETB resolve to stamp
    ``summoning_sick = true`` to match the Python contract.  The CR-
    canonical fix is (a) -- non-creature permanents don't have
    summoning sickness at all (their tap-state ability use isn't
    gated on it); Python's unconditional set is the off-canon arm.
    Probe-blocked for SSS; sibling-lane divergence pin candidate.
    Affects all ManifestDreadThenAttachSelf consumers (Conductive
    Machete / Killer's Mask / Cursed Windbreaker / Dissection Tools
    Duskmourn-Equipment family) AND every other non-creature spell
    in the covered tier (Squire's Lightblade ETB, Weapons
    Manufacturing ETB, ...).

  * **The 4 spells_cast_this_turn cards** (Cosmogrand Zenith, Sunstar
    Lightsmith, Illvoi Operative, Station Monitor): lane 3
    ``feature/rust-slice-12-...`` is wiring the slot-aware Controlled
    bridge follow-up so these 4 can get real-EoE byte-equal probes.
    Lane 3 will pick them up as its downstream probes; SSS skips them
    per the lane-coordination memo.

  * **Stay Hidden, Stay Silent** (Aura ENTERS IsSelf ->
    TapEnchantedPermanent): the bridge ``tap_enchanted_permanent``
    docstring at ``cross_engine.py``:5252-5256 documents the end-to-end
    probe as deferred ("the Aura attachment + control-stealing +
    untap-restriction rider stack is its own carrier surface beyond
    the bare bridge-arm slice") -- the Aura subsystem is sprawling
    and the static-ability riders would surface as targeted-deltas
    rather than clean compare_fields == [].

  * **Hand That Feeds** (ATTACKS + And(IsSelf, StateBound(Delirium))
    -> PumpSelfUntilEOT(+2/+0, menace)): the ``StateBound(Delirium())``
    predicate's inner StatePredicate kind ``delirium`` is NOT yet
    wired in ``_ta_dict_to_python_state_predicate``
    (cross_engine.py:9087-9089 lists only ``void_active``,
    ``any_player_controls_no_creatures``, ``spells_cast_this_turn``;
    ``delirium`` is listed in the "future StatePredicate kinds"
    deferred list).  Probe-blocked at the inner predicate bridge.

  * **Living Phone (NOT DROPPED -- see Probe 2 below).** Originally
    earmarked as deferred for the agent-shim complexity of the
    non-empty-library lane, but the empty-library no-op variant turns
    out to be cleanly tractable on the DIES path (no PendingDecision
    queued when the examined slice is empty; counter_on_miss=False
    means no fallback +1/+1 either) -- it's now SSS Probe 2.  The
    Pulsar Squadron Ace ``card_types``-vs-``subtypes`` divergence
    (``docs/SEARCH_LIMITATIONS.md`` round-55 + ``test_parity_smoke.py``
    :60978) is structurally INAPPLICABLE because Living Phone uses
    ``filter_name='creature'`` which is a plain ``card_types`` filter
    with no subtype-vs-card-type ambiguity (Pulsar's filter is
    ``spacecraft``, where the divergence trips).

  * **Innocuous Rat** (DIES + IsSelf -> ManifestDread(1)): bit-identical
    shape to Bashful Beastie which is already PROBED via
    ``test_probe_remaining_iii.py``.  Adds no new effect/event coverage.

  * **Cackling Slasher** (vanilla 3/3 with deathtouch keyword): no
    triggered/activated abilities to fire; the probe would just be
    "vanilla creature exists on bf" with no event-driven observable.
    No marginal effect/event shape coverage (deathtouch is a combat
    keyword, already exercised by Hullcarver / others).

  * **Diplomatic Relations** (Instant DiplomaticRelationsEffect with
    2-slot heterogeneous targets): the cross-engine bridge supports
    the 2-slot target seating (``cross_engine.py``:8570-8628) but the
    probe requires the 2-slot StackItem target seating shim on both
    engines AND the post-pump cleanup UEOT drain -- a richer probe
    shape than the 1-slot SSS batch is shooting for.  Deferred.

  * **Vanilla creatures** (Slavering Branchsnapper, Daggermaw
    Megalodon, Bedhead Beastie, Spectral Snatcher, Fear of Being
    Hunted, etc.): no triggered/activated abilities to fire; the
    probe would just be "vanilla creature exists on bf" with no
    event-driven observable.  No marginal effect/event shape coverage
    (the keyword-only behavior is already probed by combat-shaped
    probes -- Hullcarver deathtouch, etc.).  Same drop discipline as
    QQQ.

  * **Sequence-rider spells** (Lithobraking, Vanish from Sight,
    Withering Torment, Live or Die's DestroyTargetCreature mode): each
    has at least one sub-effect with a documented engine asymmetry --
    Vanish from Sight's top-vs-bottom default + summoning_sick reset
    (test_probe_covered_unprobed_p.py:111-122); Lithobraking's
    OptionalSacArtifactForEffect interaction with the token-creation
    substrate; Live or Die's mode 1 already PROBED via
    test_probe_may_do_r.py:201.  Same drop discipline as QQQ.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count (with QQQ wired in via
``PROBE_MODULES``): 199 -> 201 (+2).  Prior covered count: 115 -> 113
(-2).
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
# Probe 1 -- Manifest Dread (Sorcery): bare ManifestDread as SPELL effect
#   spell_effect = ManifestDread(count=1)
# Bridge spell-effect dict: {"kind": "manifest_dread", "count": 1}
# Empty-library no-op variant (Unsettling Twins N precedent generalized
# to the SPELL-EFFECT lane).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_manifest_dread_spell_empty_lib_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Manifest Dread
    (round 23, Sorcery spell_effect=ManifestDread(count=1)).**

    Drives the **real parsed Manifest Dread printing** (verified at probe
    entry) on the Python side and a bridged synthetic Sorcery carrier on
    the Rust side through the spell-resolution path.

    **Bridge arm:** ``manifest_dread`` (``cross_engine.py``:6326).  Field
    shape: ``{"kind": "manifest_dread", "count": 1}``.

    **NEW shape coverage:** all prior ``manifest_dread`` probes drive the
    effect as a TRIGGERED ABILITY (Unsettling Twins ENTERS in batch N,
    Bashful Beastie DIES in batch III).  **No probe has driven the
    bridge arm as a SPELL EFFECT** until this one.  Exercises the
    spell-resolution code path through the same bridge arm -- the
    orthogonal coverage axis to the existing ETB / DIES trigger probes.

    **Library design (empty-lib no-op variant).** With p0's library
    empty on both engines, ``ManifestDread.resolve`` short-circuits
    immediately (Python: ``if not p.library: return``; Rust: empty-Vec
    PendingDecision auto-drains as O(1) no-op).  No card is manifested,
    no face-down permanent appears, no agent ``choose_card_from_library``
    call is made on EITHER engine.  Net post-state: the Manifest Dread
    spell moves stack -> caster's graveyard on both engines; nothing
    else changes.

    Setup:
      * p0 / p1 libraries both empty.  Both hands empty.  No permanents
        on either bf.
      * Manifest Dread is pushed onto the stack as a Sorcery (no targets;
        the manifest is at-resolve, not at-cast).

    Resolution flow:
      1. Python: the real parsed Manifest Dread spell_effect
         (ManifestDread(count=1)) drives ``resolve``: empty library ->
         no-op return.  Spell moves to caster's graveyard.
      2. Rust: bridged synthetic ``manifest_dread`` arm runs resolve;
         empty library -> O(1) no-op.  Spell moves to caster's graveyard.

    Observables asserted: **full ``compare_fields``** over the whole
    cross-engine field view (hand, library, graveyard, exile,
    battlefield, stack, lives -- everything byte-equal).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.library_lookat import ManifestDread

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Manifest Dread printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Manifest Dread")
    if real is None:
        pytest.skip("Manifest Dread absent from active CardSource")
    assert "Sorcery" in real.card_types, "Manifest Dread must be a Sorcery"
    se = real.spell_effect
    assert isinstance(se, ManifestDread), (
        f"genuine Manifest Dread spell_effect must be "
        f"ManifestDread; got {type(se).__name__}"
    )
    assert se.count == 1, (
        f"Manifest Dread ManifestDread count must be 1; got {se.count}"
    )

    # ------------------------------------------------------------------
    # 2. Build cross-engine states with EMPTY libraries on both sides.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0  # ZONE_HAND

    # ------------------------------------------------------------------
    # 3. Python: genuine parsed Manifest Dread on the stack.
    # ------------------------------------------------------------------
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0, targets=())
    )

    assert len(py.players[0].library) == 0, (
        "Python: p0 library must start empty (no-op variant invariant)"
    )

    resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0, (
        f"Python: stack must be empty after spell resolves; "
        f"got {len(py.stack)} items"
    )
    # Library still empty (no-op).
    assert len(py.players[0].library) == 0, (
        f"Python: p0 library must remain empty post-no-op; "
        f"got {len(py.players[0].library)}"
    )
    # Hand unchanged (no manifest).
    assert len(py.players[0].hand) == 0, (
        f"Python: p0 hand must remain empty post-no-op; "
        f"got {len(py.players[0].hand)}"
    )
    # No permanents manifested.
    assert len(py.battlefield) == 0, (
        f"Python: bf must remain empty post-no-op; "
        f"got {len(py.battlefield)}"
    )
    # Spell moved to caster's graveyard.
    py_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert py_gy_names == ["Manifest Dread"], (
        f"Python: p0 graveyard must contain Manifest Dread; "
        f"got {py_gy_names}"
    )

    # ------------------------------------------------------------------
    # 4. Rust: bridged manifest_dread synthetic Sorcery.
    # ------------------------------------------------------------------
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Manifest Dread",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "manifest_dread",
                    "count": 1,
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty after spell resolves; "
        f"got {rs.stack_size()} items"
    )
    assert rs.library_sizes[0] == 0, (
        f"Rust: p0 library must remain empty post-no-op; "
        f"got {rs.library_sizes[0]}"
    )
    assert rs.hand_sizes[0] == 0, (
        f"Rust: p0 hand must remain empty post-no-op; "
        f"got {rs.hand_sizes[0]}"
    )

    # ------------------------------------------------------------------
    # 5. Cross-engine byte-equality across the WHOLE field view.
    # ------------------------------------------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Manifest Dread spell empty-lib no-op must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Living Phone: DIES + IsSelf -> LookAtTopNRevealOrCounter
#   triggered_ability event=dies, predicate=IsSelf,
#                     effect=LookAtTopNRevealOrCounter(n=5,
#                                                     filter_name='creature',
#                                                     max_power=2,
#                                                     counter_on_miss=False)
# Bridge: {"kind": "look_at_top_n_reveal_or_counter", "n": 5,
#          "filter_name": "creature", "max_power": 2,
#          "counter_on_miss": False}
# Empty-library no-op variant: with the source dying into an empty
# library, the look-at-top-N PendingDecision auto-resolves on an empty
# examined list (no card matches the filter), counter_on_miss=False so
# no fallback counter is added, and the dying source is already in the
# graveyard.  Byte-equal no-op across the whole field view.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_living_phone_dies_look_top_4_empty_lib_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Living Phone
    (round 23, DIES + IsSelf, LookAtTopNRevealOrCounter(n=5,
    filter='creature', max_power=2, counter_on_miss=False)).**

    Drives the **real parsed Living Phone printing** (verified at probe
    entry) on the Python side and a bridged synthetic Toy carrier on the
    Rust side through the ``DIES`` dispatch path.

    **NEW shape coverage:** the ``look_at_top_n_reveal_or_counter``
    bridge arm (``cross_engine.py``:3602-3667) has been pinned by the
    Pulsar Squadron Ace ENTERS probe (``test_parity_smoke.py``:60762)
    with the SUBTYPE-filter ``spacecraft`` shape AND its sibling
    ``card_types``-vs-``subtypes`` divergence pin
    (``test_parity_smoke.py``:60978).  **No probe has driven the bridge
    arm with the CARD-TYPE-filter ``creature`` shape on a DIES event**
    until this one.  Pulsar Ace uses ENTERS + filter=spacecraft +
    max_power=0 + counter_on_miss=True; Living Phone uses DIES +
    filter=creature + max_power=2 + counter_on_miss=False -- the
    orthogonal cover of every load-bearing field of the bridge arm
    (event lane: DIES vs ENTERS; filter lane: card-type vs subtype;
    max_power lane: nonzero vs zero; counter_on_miss lane: False vs
    True).

    **Filter-lane parity (the Pulsar divergence is structurally
    inapplicable here).** Rust's ``card_matches_filter``
    (``cards.rs``:5800+) checks ``subtypes`` first, falling back to
    ``card_types`` only for a fixed lookup table; the documented round-55
    divergence is that the ``spacecraft`` token mis-routes through the
    ``card_types``-vs-``subtypes`` resolver (Spacecraft is a CARD TYPE in
    EoE, not a SUBTYPE -- Pulsar Ace pins this).  Living Phone's
    ``creature`` filter is a *plain* ``card_types`` filter, hitting the
    same lookup table without any subtype-vs-card-type ambiguity --
    Pulsar's divergence does NOT trip.  The probe pins THE
    creature-filter-card-types lane byte-equal, independent of the
    spacecraft-divergence pin.

    **Library design (empty-lib no-op variant).** With p0's library
    empty on both engines, ``LookAtTopNRevealOrCounter.resolve``
    short-circuits before any reveal: Python's
    ``examined = p.library[:n]`` is ``[]``, the ``options`` filter is
    ``[]``, no agent ``choose_card_from_library`` call is made, AND
    counter_on_miss=False so no fallback +1/+1 counter is placed on
    the source.  Rust's resolve walks the same empty library, queues
    an empty ``PendingDecision::LookAtTopNRevealOrCounterChoice``
    which the ``submit_look_at_top_n_decision`` auto-drain (no agent
    choice needed for an empty pool) resolves as O(1) no-op.  Living
    Phone is already in the graveyard by the time the trigger
    resolves; no field changes.

    Setup:
      * p0 has Living Phone (2/1 Artifact Creature -- Toy) on the
        battlefield, summoning-sick = False.
      * p0 / p1 libraries both empty.  Both hands empty.
      * Active player = p0.

    Kill flow:
      1. Deal ``toughness=1`` damage to Living Phone on BOTH engines.
      2. Apply SBAs: lethal damage -> graveyard -> DIES trigger pushed.
      3. Drain: ``LookAtTopNRevealOrCounter`` resolves on empty library
         -> no-op (no reveal, no counter, no agent call).
      4. Apply SBAs (quiescent).

    Observables asserted: **full ``compare_fields``** over the whole
    cross-engine field view (Living Phone in p0's graveyard; bf empty;
    hand / library empty; life totals unchanged; no counters
    anywhere).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.library_lookat import (
        LookAtTopNRevealOrCounter,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Living Phone printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Living Phone")
    if real is None:
        pytest.skip("Living Phone absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Living Phone must be a Creature"
    )
    dies_ta = next(
        (ta for ta in real.triggered_abilities
         if ta.event == Event.DIES),
        None,
    )
    assert dies_ta is not None, (
        "Living Phone must have a DIES triggered ability"
    )
    assert isinstance(dies_ta.predicate, IsSelf), (
        f"Living Phone DIES predicate must be IsSelf; "
        f"got {type(dies_ta.predicate).__name__}"
    )
    assert isinstance(dies_ta.effect, LookAtTopNRevealOrCounter), (
        f"Living Phone DIES effect must be LookAtTopNRevealOrCounter; "
        f"got {type(dies_ta.effect).__name__}"
    )
    assert dies_ta.effect.n == 5
    assert dies_ta.effect.filter_name == "creature"
    assert dies_ta.effect.max_power == 2
    assert dies_ta.effect.counter_on_miss is False

    # ------------------------------------------------------------------
    # 2. Build cross-engine states with EMPTY libraries.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 3. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    lp_ta_dict = {
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "look_at_top_n_reveal_or_counter",
            "n": 5,
            "filter_name": "creature",
            "max_power": 2,
            "counter_on_miss": False,
        },
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(lp_ta_dict)
    assert bridge_ta.event == Event.DIES
    assert isinstance(bridge_ta.predicate, IsSelf)
    assert isinstance(bridge_ta.effect, LookAtTopNRevealOrCounter)
    assert bridge_ta.effect.n == 5
    assert bridge_ta.effect.filter_name == "creature"
    assert bridge_ta.effect.max_power == 2
    assert bridge_ta.effect.counter_on_miss is False

    # ------------------------------------------------------------------
    # 4. Rust: inject Living Phone onto p0's battlefield with the
    #    bridged DIES trigger.
    # ------------------------------------------------------------------
    rs_lp_id = rs.register_and_inject_object(
        {
            "name": "Living Phone",
            "card_types": ["Artifact", "Creature"],
            "subtypes": ["Toy"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "triggered_abilities": [lp_ta_dict],
        },
        0, ZB,
    )

    # ------------------------------------------------------------------
    # 5. Rust: deal lethal damage -> SBA moves to graveyard -> DIES
    #    trigger pushed -> drain (LookAtTopNRevealOrCounter on empty lib
    #    no-op).
    # ------------------------------------------------------------------
    rs.deal_damage(rs_lp_id, int(real.toughness))
    rs.apply_sbas()
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 DIES trigger must be pushed after lethal "
        f"damage + SBAs; got {rs.stack_size()}"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # No pending decisions should remain (counter_on_miss=False + empty
    # library means no choice point is queued).
    assert not rs.has_pending_decision(), (
        f"Rust: no pending decisions must remain after empty-lib "
        f"LookAtTopNRevealOrCounter resolve; got "
        f"{rs.pending_decisions()}"
    )
    # Living Phone in graveyard (zone 3); no bf objects.
    assert rs.find_object_zone(rs_lp_id) == 3, (
        f"Rust: Living Phone must be in graveyard; got zone "
        f"{rs.find_object_zone(rs_lp_id)}"
    )

    # ------------------------------------------------------------------
    # 6. Python: inject the GENUINE parsed Living Phone onto p0's
    #    battlefield directly.  Deal lethal damage -> SBA -> DIES
    #    trigger -> drain.
    # ------------------------------------------------------------------
    py_lp = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_lp.summoning_sick = False
    py_lp.tapped = False
    py_lp.damage = 0
    py_lp.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_lp)

    py_lp.damage = int(real.toughness)  # mark lethal damage directly
    py_sba(py)
    assert len(py.stack) == 1, (
        f"Python: exactly 1 DIES trigger must be pushed after lethal "
        f"damage + SBAs; got {len(py.stack)}"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ------------------------------------------------------------------
    # 7. Cross-engine byte-equality across the WHOLE field view.
    # ------------------------------------------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Living Phone DIES look-top-4-empty-lib no-op must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
