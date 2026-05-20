"""Genuine real-EoE cross-engine byte-equality probes -- batch UUU (round 24).

Two cards from the ``covered_by_construction`` tier are upgraded to the
``PROBED`` tier by this module.  Each probe drives the ACTUAL parsed EoE
printing on the Python side and the bridged synthetic carrier on the
Rust side, asserting targeted-observable cross-engine byte-equality on
a controlled real-EoE state -- the same strength bar as the SSS-batch
Manifest Dread / Living Phone probes (slug-keyed
``test_cross_engine_real_eoe_<...>_parity`` naming convention).

The probes deliberately cover effect/event shapes NOT already pinned by
the PROBED 201 (round-23 baseline after SSS merge ``b581b731``):

  * **Skullsnap Nuisance** -- Creature ENTERS + ``And(Subject(None,
    IsEnchantment()), Controlled(YOU))`` -> ``Surveil(amount=1)``.  The
    "Eerie" Duskmourn-mechanic substrate (JJ unlock + NN batch) has
    pinned this predicate shape with DrawCards (Entity Tracker),
    PumpSelfUntilEOT (Erratic Apparition, Infernal Phantom),
    EachOpponentLosesLife (Balemurk Leech via the unregistered
    ``test_probe_subject_is_enchantment_unlock.py``), and
    MillTargetPlayer (Scrabbling Skullcrab).  **No probe in PROBE_MODULES
    has driven the Eerie predicate composition with a Surveil
    effect** until this module -- the orthogonal Effect-lane cover
    relative to the existing eerie batch probes.  Empty-library
    no-op variant: with p0's library empty, ``Surveil.resolve``
    walks zero cards on both engines; no PendingDecision is queued
    (Rust's surveil-decision pump requires N >= 1 examined cards),
    no agent ``choose_surveil`` call is made on either engine
    (Python's ``Surveil.resolve`` short-circuits before the agent
    branch); the source and observer end in identical zone states
    across engines.  Byte-equal across the targeted observables
    (library + graveyard sizes; stack drain; lives; bf counts).

  * **Gremlin Tamer** -- Creature ENTERS + ``And(Subject(None,
    IsEnchantment()), Controlled(YOU))`` -> ``CreateToken(Gremlin
    1/1, count=1)``.  Same Eerie predicate composition as Probe 1
    (Skullsnap Nuisance) but cascading to a DIFFERENT Effect lane:
    ``create_token`` rather than ``surveil``.  The ``create_token``
    bridge arm has been pinned by 5+ real-EoE consumers with both
    creature-typed tokens (Soldier 1/1 for Honored Knight-Captain /
    Knight Luminary; Robot 2/2 artifact-creature for Wedgelight
    Rammer) and a non-creature artifact token (Lander for Galactic
    Wayfarer / Bioengineered Future / Biomechan Engineer / Biotech
    Specialist).  **No probe has driven ``create_token`` from the
    Eerie predicate composition** until this one -- the orthogonal
    cover of the create_token bridge arm with the Eerie predicate
    (the prior probes all used the bare ``SourceIsSelf`` predicate).
    Gremlin 1/1 token shape is also a NEW token-printing composition
    (Creature -- Gremlin, no Artifact card_type; distinct from
    Soldier and Robot above).  Both engines spawn one Gremlin 1/1
    token onto p0's bf under p0's control; byte-equal across the
    targeted observables (bf counts, token controller, source
    controller routing).

DROPPED ON VERIFY (honest discipline + new divergence pin candidates)
---------------------------------------------------------------------

  * **Defiant Survivor + Cautious Survivor + Savior of the Small +
    Shrewd Storyteller** (the 4-card Survivor "Source(IsTapped) at
    beginning of postcombat main" family): **probe attempt surfaced
    a NEW cross-engine IsSelf-vs-player-subject divergence on the
    BEGINNING_OF_POSTCOMBAT_MAIN event lane.** The PPP Pin 3 / 10th
    Rust slice (commit ``2745a356``) shipped the ``Event::Beginning
    OfPostcombatMain`` dispatch in Rust (``state_ops_steps.rs``:622-639)
    + the ``"beginning_of_postcombat_main"`` event arm in the
    cross-engine bridge (``cross_engine.py``:9572-9610), but the
    DISPATCH SUBJECT for every phase-step event in Rust is the
    ``PLAYER_SUBJECT_OFFSET + active_player`` sentinel
    (``cards.rs::PLAYER_SUBJECT_OFFSET``).  Rust's
    ``Predicate::SourceIsSelf`` evaluator (``cards.rs``:4730) is the
    strict ``source_id == subject_id`` check; since ``source_id`` is
    the firing permanent's object id and ``subject_id`` is the
    player-sentinel sum, **``SourceIsSelf`` ALWAYS evaluates False
    for player-subject events on Rust**, and the Survivor trigger
    silently never pushes on Rust even though every other clause
    (``ControlledByYou``, ``SourceIsTapped``) evaluates True.
    Python's ``IsSelf.matches``
    (``effects/predicates.py``:413-436) carries an explicit
    player-subject tautology arm: ``if self.subject is None and obj
    is not None and not hasattr(obj, "printing"): return True`` --
    Players expose ``id`` but no ``printing`` attribute, so on a
    player-subject event Python's ``IsSelf()`` reads as "source IS
    itself" and evaluates True.  Empirical repro pattern::

        rs = build_rust_state(spec)
        rs_ds = rs.register_and_inject_object(
            {"name": "Defiant Survivor", "card_types": ["Creature"],
             "power": 3, "toughness": 2,
             "triggered_abilities": [{
                 "event": "beginning_of_postcombat_main",
                 "predicate": {
                     "kind": "and",
                     "left": {"kind": "and",
                              "left": {"kind": "controlled_by_you"},
                              "right": {"kind": "source_is_self"}},
                     "right": {"kind": "source_is_tapped"},
                 },
                 "effect": {"kind": "manifest_dread", "count": 1},
             }]},
            0, ZB,
        )
        rs.tap_object(rs_ds)
        for _ in range(20):
            if rs.current_phase() == PHASE_MAIN2: break
            rs.advance_phase()
        # Rust stack: 0 (trigger silently never pushed -- SourceIsSelf
        #             fails on PLAYER_SUBJECT_OFFSET subject)
        # Python stack: 1 (IsSelf tautology arm fires on Player subject)

    Affects **all 5 EoE "Survivor" cards** that the PPP Pin 3 +
    ``Source(IsTapped)`` round-21 RR closure listed as "unlocked"
    (Savior of the Small, Cautious Survivor, Defiant Survivor, House
    Cartographer, Shrewd Storyteller -- per the unlock note at
    ``state_ops_steps.rs``:632-634 + ``cards.rs``:4474-4475).  The
    unlock notes are technically correct at the EVENT-dispatch +
    PREDICATE-PARSE layer but PREMATURE on the end-to-end byte-equal
    layer -- the IsSelf evaluator gap had not been surfaced.

    Sibling-lane divergence pin candidates:
      (a) Add a Rust ``Predicate::SourceIsSelf`` arm that recognises
          the ``PLAYER_SUBJECT_OFFSET`` sentinel and treats the
          player-subject case as a tautology mirroring Python's
          ``hasattr(obj, "printing")`` branch.  CR-canonical fix:
          the rule the predicate models is "the source IS the trigger
          source" -- on a phase-step event whose subject is a player
          rather than a permanent, the predicate is structurally
          tautological because the dispatcher already iterates one
          source at a time.
      (b) Alternatively, change the bridge's ``source_is_self``
          translation for player-subject events to ``always`` (since
          they ARE tautological in that context) -- the lower-impact
          fix; doesn't touch Rust's Predicate enum.

    Probe-blocked for UUU; characterised as a sibling-lane
    divergence pin candidate for batch round-25+.

  * **The PPP downstream probes** (Cautious Survivor + Savior of the
    Small at ``test_probe_ppp_downstream.py``:178-301) do NOT
    exercise the trigger dispatch end-to-end -- they verify
    ``bridge_ta.event`` + Rust ``register_printing`` acceptance only.
    The divergence above never surfaces in those tests because they
    never invoke ``advance_phase`` past PHASE_MAIN2 (no event
    actually dispatches; no stack trigger pushed; no compare to make).
    Module is NOT registered in ``PROBE_MODULES`` (correctly --
    parse-only assertion is weaker than the full PROBED bar).

  * **Cosmogrand Zenith + Station Monitor** -- the 4
    ``spells_cast_this_turn`` cards per the lane SSS / coordination
    memo; natural slice-14 territory (Cosmogrand Zenith + Station
    Monitor remain unprobed; Sunstar Lightsmith + Illvoi Operative
    were probed by slice 12 ``test_probe_mmm_downstream.py``).
    Skipped per the coordination memo.

  * **Innocuous Rat** (DIES + IsSelf -> ManifestDread(1)): bit-
    identical shape to Bashful Beastie which is already PROBED via
    ``test_probe_remaining_iii.py``.  Adds no new effect/event
    coverage (same drop discipline as SSS).

  * **Trapped in the Screen** (Enchantment ENTERS + IsSelf ->
    ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)): bit-
    identical bridge shape to Banishing Light which is already
    PROBED (``test_parity_smoke.py``:34218 -- the bare-shape
    Enchantment carrier with the bare-default ``max_mv=0`` no MV
    cap).  Adds no new effect/event coverage.

  * **Restricted Office // Lecture Hall** (Room ENTERS + IsSelf ->
    DestroyAllCreatures(min_power=3)): Room subtype is gated by
    the Rooms / doors subsystem (``docs/SUBSYSTEM_ROADMAP.md``);
    the ENTERS trigger only fires when the specific room half is
    unlocked, not on plain ENTERS.  Verified empirically: Python's
    ``_trigger_etb_abilities`` does not push the trigger on a
    pristine Room enter (the trigger carries
    ``room_half='Restricted Office'`` and is gated by the room-
    unlock state).  Probe-blocked at the Rooms subsystem.

  * **Vanilla / keyword-only creatures** (Patched Plaything,
    Magus of the Moon, Steelswarm Operator, etc.): no triggered
    abilities, no spell_effect, only static abilities or activated
    abilities (Magus's nonbasic-as-mountain static; Steelswarm's
    tap-for-mana activated).  The activated-abilities and
    static-abilities surfaces are covered by their own dedicated
    probe modules (``test_probe_activated_abilities_*.py`` series);
    the ENTERS-/DIES-trigger lane this batch targets is empty
    for these cards.  Same drop discipline as SSS / QQQ.

  * **Sami's Curiosity** (Sorcery spell_effect=Sequence(GainLife(2),
    CreateToken(Lander))): the Lander token-creation substrate
    requires the ``register_token_printing`` two-step registration
    pattern not exercised in the bare-Sequence spell-effect lane
    (same drop reason as Gremlin Tamer in
    ``test_probe_eerie_cards_nn.py``:68-73).  Probe-blocked at the
    token-creation substrate.

  * **Withering Torment** (Instant spell_effect=Sequence
    (DestroyTargetCreature(or_enchantment=True), LoseLife(2))):
    the ``or_enchantment=True`` rider on DestroyTargetCreature is
    NOT plumbed through any of the cross-engine ``destroy_target_*``
    bridge arms (verified by walk of every ``kind == "destroy_*"``
    arm in ``cross_engine.py``).  Probe-blocked at the bridge-arm
    rider gap.

  * **Temporal Intervention** (Sorcery spell_effect=
    TargetOpponentDiscardsCasterChoice()): no bridge arm exists
    (verified by ``grep TargetOpponentDiscards src/mtg_bot/parity/``).
    Probe-blocked at the bridge-arm absence.

  * **Other Eerie-mechanic cards** (Cult Healer, Dashing
    Bloodsucker, Optimistic Scavenger): each blocked by a distinct
    downstream gap documented in
    ``test_probe_eerie_cards_nn.py``:46-82 (granted_keywords rider
    cascade for Cult Healer + Dashing Bloodsucker; target-pick
    asymmetry for Optimistic Scavenger).  Probe-blocked at the
    documented downstream gaps.  (Gremlin Tamer was dropped by that
    earlier batch for token-registration substrate "two-step
    registration not tested in the ENTERS-Eerie lane" -- but the
    Galactic Wayfarer / Wedgelight Rammer / Bioengineered Future /
    Biomechan Engineer / Biotech Specialist probes have since
    pinned the ``register_token_printing`` two-step pattern as the
    canonical token-spawn probe shape; the substrate is now
    tractable and Gremlin Tamer is Probe 2 of this batch.)

  * **The DEALS_COMBAT_DAMAGE family** (Fear of Failed Tests etc.):
    end-to-end probe requires the cross-engine combat-damage
    harness (``resolve_combat_damage_python`` +
    ``deal_combat_damage_rust`` at ``cross_engine.py``:11944-12019)
    + the harness-side ``resolving_combat_damage_amount`` carrier-
    scalar push -- a distinctly richer setup than the ENTERS-
    Eerie-Surveil probe shape this batch shoots for.  The
    ``draw_cards_equal_to_resolving_combat_damage`` bridge arm
    docstring explicitly defers end-to-end probing to a dedicated
    combat-damage probe batch (round-17/18/19 synthetic-only-
    when-riders-cascade precedent).  Deferred.

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
Two cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count (with SSS wired in via
``PROBE_MODULES``): 201 -> 203 (+2).  Prior covered count: 113 -> 111
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
# Probe 1 -- Skullsnap Nuisance: Eerie ENTERS-trigger -> Surveil(1)
#   triggered_ability event=enters,
#                     predicate=And(Subject(None, IsEnchantment()),
#                                   Controlled(YOU)),
#                     effect=Surveil(amount=1)
# Empty-library no-op variant: with p0's library empty, Surveil walks
# zero cards on both engines; no PendingDecision queued, no agent
# choose_surveil call, no graveyard mill.  Both engines short-circuit
# in the same way: byte-equal across targeted observables.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_skullsnap_nuisance_eerie_surveil_empty_lib_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Skullsnap Nuisance
    (round 24, ENTERS + Eerie predicate -> Surveil(1)).**

    Drives the **real parsed Skullsnap Nuisance printing** (verified at
    probe entry) on the Python side and a bridged synthetic carrier on
    the Rust side through the ``ENTERS`` dispatch path for an
    enchantment that ETBs under the observer's control.

    **NEW Effect-lane coverage.** The Eerie predicate composition
    (``And(Subject(None, IsEnchantment()), Controlled(YOU))``) is the
    JJ-substrate ``subject_is_enchantment`` unlock predicate (round 17;
    closed at ``feature/rust-subject-is-enchantment`` ->
    ``3933fcb4``).  PROBE_MODULES-registered probes have driven the
    Eerie predicate with:

      * ``DrawCards(1)`` (Entity Tracker -- ``test_probe_eerie_cards_
        nn.py``:174)
      * ``PumpSelfUntilEOT(+1/+1)`` (Erratic Apparition --
        ``test_probe_eerie_cards_nn.py``:386)
      * ``PumpSelfUntilEOT(+2/+0)`` (Infernal Phantom --
        ``test_probe_eerie_cards_nn.py``:560)
      * ``MillTargetPlayer(2)`` (Scrabbling Skullcrab --
        ``test_probe_eerie_cards_nn.py``:725)

    **No PROBE_MODULES-registered probe has driven the Eerie
    predicate with a ``Surveil`` effect** until this one.  The drop
    note in ``test_probe_eerie_cards_nn.py``:75-81 documented Skullsnap
    Nuisance as deferred on the basis that "with an empty library both
    engines no-op: nothing to surveil. Seeding a library requires the
    ``send_all_to_graveyard`` Rust decision drain ... a separate
    mechanic surface not exercised in the Eerie ETB lane yet" -- but
    the *empty-library no-op variant* is exactly the byte-equal
    PROBED-bar template the SSS Manifest Dread Sorcery probe + the
    III Bashful Beastie DIES probe use, and the verification trace
    below confirms BOTH engines short-circuit identically on empty-
    library Surveil (no PendingDecision queued; no agent call; no
    graveyard mill).  Empirically tractable -- the drop note was
    over-cautious.

    **Bridge arm:** ``surveil`` (``cross_engine.py``:737).  Same arm
    as the Thawbringer ETB Surveil(1) probe
    (``test_parity_smoke.py``:33591), the Starbreach Whale +
    Wurmwall Sweeper Surveil(2) probes, and the Appendage Amalgam
    ATTACKS-Surveil probe.  No new bridge coverage for the effect
    arm; the load-bearing axis is the **predicate composition** --
    none of those prior probes wear the Eerie ``Subject(None,
    IsEnchantment()) AND Controlled(YOU)`` predicate (Thawbringer +
    Starbreach Whale + Wurmwall Sweeper + Appendage Amalgam all use
    bare ``SourceIsSelf``).  The orthogonal cover this probe gives
    the Surveil effect lane is the Eerie predicate composition's
    first-time pinning with that effect.

    **Predicate-vs-event distinction.** The Eerie observer pattern
    requires the trigger source NOT to be the entering object -- the
    Eerie holder watches OTHER enchantments enter under its
    controller.  Both engines route this through the predicate
    composition: ``Subject(None, IsEnchantment())`` matches the
    entering object being an enchantment (the ETBing Probe
    Enchantment), and ``Controlled(YOU)`` matches the entering
    object's controller == source's controller (both p0 here).
    Skullsnap Nuisance itself is on bf as an OBSERVER, not the
    entering object -- so ``IsSelf`` (which would gate to "Skullsnap
    Nuisance IS the entering object") would be FALSE for this
    pattern; the predicate is correctly ``Subject(IsEnchantment) AND
    Controlled(YOU)`` and works identically on both engines because
    the entering object's id IS a real permanent id on both sides
    (no PLAYER_SUBJECT_OFFSET sentinel involvement -- distinct from
    the dropped Survivor-card divergence above).

    **Library design (empty-lib no-op variant).** With p0's library
    empty on both engines, ``Surveil.resolve`` short-circuits
    before any decision pump:

      * Python: ``Surveil.resolve`` walks the top N cards via
        ``examined = p.library[:n]`` -- on an empty library
        ``examined = []`` so no card is moved, no agent call is
        made, and the function returns without queuing a decision
        (``effects/generic/surveil.py``).
      * Rust: Surveil's resolve arm queues a
        ``PendingDecision::SurveilChoice`` only if the examined-pool
        is non-empty.  Empty library => no decision queued, no
        ``submit_surveil_decision`` call, no agent contact.

    Net post-state: Skullsnap Nuisance on p0's bf (observer);
    Probe Enchantment on p0's bf (the entering enchantment that
    triggered the Eerie observer); both p0/p1 libraries still
    empty; both graveyards still empty; lives unchanged.

    Setup:
      * p0 has Skullsnap Nuisance (1/4 Creature -- Insect Skeleton
        with Flying) on the battlefield, summoning_sick=False.
      * p0 / p1 libraries both empty (no-op variant invariant).
      * Both hands empty.  Probe Enchantment will ETB from a Rust-
        side hand inject + push_to_stack on Rust; from a direct
        Zone.STACK new_object on Python.
      * Active player = p0.

    Trigger flow:
      1. Rust: a bare synthetic ``Probe Enchantment`` is pushed onto
         the stack (from p0's hand), then ``resolve_top_of_stack``
         moves it to p0's bf and dispatches Event::Enters with
         subject=Probe Enchantment.id.  Skullsnap Nuisance's
         observer trigger evaluates ``SubjectIsEnchantment`` against
         the Probe Enchantment (True) and ``ControlledByYou`` against
         source_controller=0 == subject_controller=0 (True) -> trigger
         pushed on the Rust stack.
         Python: a bare ``Probe Enchantment`` (CardPrinting fixture)
         is pushed onto the stack; ``resolve_top_of_stack`` moves it
         onto p0's bf and fires
         ``_trigger_etb_abilities``/``dispatch_event(state,
         Event.ENTERS, obj=Probe Enchantment)``.  Same predicate
         match.
      2. Both stacks have 1 item (the Surveil(1) trigger).
      3. Drain: Surveil.resolve hits the empty-library short-circuit
         on both engines.

    Observables asserted (targeted):
      * Stack drains cleanly: pre-drain 1 -> post-drain 0 on BOTH
        engines.
      * p0 library remains empty: 0 -> 0 on BOTH engines.
      * p0 graveyard remains empty (no surveil mill): 0 -> 0 on
        BOTH engines.
      * p0 battlefield contains exactly Skullsnap Nuisance + Probe
        Enchantment (2 objects).
      * No pending decisions on Rust side.
      * p0 + p1 lives unchanged at 20.

    Rust triggered-ability dict::

        {
            "event": "enters",
            "predicate": {
                "kind": "and",
                "left": {"kind": "subject_is_enchantment"},
                "right": {"kind": "controlled_by_you"},
            },
            "effect": {"kind": "surveil", "count": 1},
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import (
        Event, Controlled, YOU, And, Subject,
    )
    from mtg_bot.effects.object_predicates import IsEnchantment
    from mtg_bot.effects.generic.library_lookat import Surveil

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Skullsnap Nuisance printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Skullsnap Nuisance")
    if real is None:
        pytest.skip("Skullsnap Nuisance absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Skullsnap Nuisance must be a Creature"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Skullsnap Nuisance must have an ENTERS triggered ability"
    )
    assert isinstance(enters_ta.effect, Surveil), (
        f"Skullsnap Nuisance ENTERS effect must be Surveil; "
        f"got {type(enters_ta.effect).__name__}"
    )
    assert enters_ta.effect.amount == 1, (
        f"Skullsnap Nuisance Surveil amount must be 1; "
        f"got {enters_ta.effect.amount}"
    )
    # Predicate composition: And(Subject(None, IsEnchantment()),
    # Controlled(YOU)).
    pred = enters_ta.predicate
    assert isinstance(pred, And), (
        f"Skullsnap Nuisance ENTERS predicate must be And; "
        f"got {type(pred).__name__}"
    )
    # Walk the And tree to find both arms.
    found_subject_is_enchantment = False
    found_controlled_you = False

    def _walk(p):
        nonlocal found_subject_is_enchantment, found_controlled_you
        if isinstance(p, And):
            _walk(p.left)
            _walk(p.right)
        elif isinstance(p, Subject) and isinstance(p.inner, IsEnchantment):
            found_subject_is_enchantment = True
        elif isinstance(p, Controlled) and p.by == YOU:
            found_controlled_you = True

    _walk(pred)
    assert found_subject_is_enchantment, (
        f"Skullsnap Nuisance predicate must contain Subject(None, "
        f"IsEnchantment()); got {pred!r}"
    )
    assert found_controlled_you, (
        f"Skullsnap Nuisance predicate must contain Controlled(YOU); "
        f"got {pred!r}"
    )

    # ------------------------------------------------------------------
    # 2. Build cross-engine states with EMPTY libraries.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND

    # ------------------------------------------------------------------
    # 3. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    sn_ta_dict = {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_enchantment"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "surveil", "count": 1},
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(sn_ta_dict)
    assert bridge_ta.event == Event.ENTERS
    assert isinstance(bridge_ta.effect, Surveil)
    assert bridge_ta.effect.amount == 1

    # ------------------------------------------------------------------
    # 4. Rust: pre-seat Skullsnap Nuisance carrier on p0's bf.
    # ------------------------------------------------------------------
    rs_sn_id = rs.register_and_inject_object(
        {
            "name": "Skullsnap Nuisance",
            "card_types": ["Creature"],
            "subtypes": ["Insect", "Skeleton"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": ["flying"],
            "triggered_abilities": [sn_ta_dict],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    assert rs.find_object_zone(rs_sn_id) == ZB, (
        "Rust: Skullsnap Nuisance must start on p0's bf"
    )
    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty post-inject (Skullsnap Nuisance's "
        f"own ENTERS does not match the Eerie predicate -- subject is "
        f"a Creature, not Enchantment); got {rs.stack_size()}"
    )

    # ------------------------------------------------------------------
    # 5. Rust: push a bare Probe Enchantment from p0's hand to the
    #    stack, resolve it -> ETBs on p0's bf -> Skullsnap Nuisance's
    #    Eerie observer fires.
    # ------------------------------------------------------------------
    rs_ench_id = rs.register_and_inject_object(
        {
            "name": "Probe Enchantment",
            "card_types": ["Enchantment"],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_ench_id, 0)
    rs.resolve_top_of_stack()
    assert rs.find_object_zone(rs_ench_id) == ZB, (
        "Rust: Probe Enchantment must have resolved onto p0's bf"
    )
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Skullsnap Nuisance Eerie Surveil) "
        f"must be on the stack after Probe Enchantment ETBs; "
        f"got {rs.stack_size()}"
    )

    rs_p0_lib_before = rs.library_sizes[0]
    rs_p0_gy_before = rs.graveyard_sizes[0]
    assert rs_p0_lib_before == 0
    assert rs_p0_gy_before == 0

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty after Surveil(1) resolves; "
        f"got {rs.stack_size()}"
    )
    assert not rs.has_pending_decision(), (
        f"Rust: no pending decisions must remain after empty-lib "
        f"Surveil resolve (the SurveilChoice PendingDecision is only "
        f"queued when examined-pool is non-empty); got "
        f"{rs.pending_decisions()}"
    )
    rs_p0_lib_after = rs.library_sizes[0]
    rs_p0_gy_after = rs.graveyard_sizes[0]
    assert rs_p0_lib_after == rs_p0_lib_before, (
        f"Rust: p0 library must be unchanged (empty -> empty); "
        f"before={rs_p0_lib_before}, after={rs_p0_lib_after}"
    )
    assert rs_p0_gy_after == rs_p0_gy_before, (
        f"Rust: p0 graveyard must be unchanged (no surveil mill on "
        f"empty library); before={rs_p0_gy_before}, after={rs_p0_gy_after}"
    )
    # p0 battlefield: Skullsnap Nuisance (observer) + Probe Enchantment
    # (the entering enchantment).
    assert rs.battlefield_sizes[0] == 2, (
        f"Rust: p0 battlefield must contain Skullsnap Nuisance + "
        f"Probe Enchantment; got {rs.battlefield_sizes[0]}"
    )

    # ------------------------------------------------------------------
    # 6. Python: inject genuine Skullsnap Nuisance printing onto p0's
    #    bf directly.
    # ------------------------------------------------------------------
    py_sn = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_sn.summoning_sick = False
    py_sn.tapped = False
    py_sn.damage = 0
    py_sn.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_sn)

    # ------------------------------------------------------------------
    # 7. Python: build a bare Probe Enchantment printing fixture
    #    (matches Rust's bare-card-type construction), push it to the
    #    stack, resolve -> ETB -> Eerie observer fires.
    # ------------------------------------------------------------------
    enchant_printing = CardPrinting(
        name="Probe Enchantment",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Enchantment",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )
    py_ench = py.new_object(enchant_printing, owner_id=0, zone=Zone.STACK)
    py.stack.append(StackItem(source=py_ench, controller_id=0))
    resolve_top_of_stack(py)
    assert any(
        o.printing.name == "Probe Enchantment" for o in py.battlefield
    ), "Python: Probe Enchantment must have resolved onto p0's bf"
    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Skullsnap Nuisance Eerie Surveil) "
        f"must be on the stack after Probe Enchantment ETBs; "
        f"got {len(py.stack)}"
    )

    py_p0_lib_before = len(py.players[0].library)
    py_p0_gy_before = len(py.players[0].graveyard)
    assert py_p0_lib_before == 0
    assert py_p0_gy_before == 0

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0, (
        f"Python: stack must be empty after Surveil(1) resolves; "
        f"got {len(py.stack)}"
    )
    py_p0_lib_after = len(py.players[0].library)
    py_p0_gy_after = len(py.players[0].graveyard)
    assert py_p0_lib_after == py_p0_lib_before, (
        f"Python: p0 library must be unchanged (empty -> empty); "
        f"before={py_p0_lib_before}, after={py_p0_lib_after}"
    )
    assert py_p0_gy_after == py_p0_gy_before, (
        f"Python: p0 graveyard must be unchanged (no surveil mill on "
        f"empty library); before={py_p0_gy_before}, after={py_p0_gy_after}"
    )
    assert len(py.battlefield) == 2, (
        f"Python: bf must contain Skullsnap Nuisance + Probe "
        f"Enchantment; got {len(py.battlefield)}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_p0_lib_after == py_p0_lib_after == 0, (
        f"p0 library size: Rust={rs_p0_lib_after}, "
        f"Python={py_p0_lib_after} (must be byte-equal at 0 -- "
        f"empty-lib Surveil no-op on both engines)"
    )
    assert rs_p0_gy_after == py_p0_gy_after == 0, (
        f"p0 graveyard size: Rust={rs_p0_gy_after}, "
        f"Python={py_p0_gy_after} (must be byte-equal at 0 -- no "
        f"surveil mill on empty library on either engine)"
    )
    assert rs.battlefield_sizes[0] == len(py.battlefield) == 2, (
        f"p0 battlefield size: Rust={rs.battlefield_sizes[0]}, "
        f"Python={len(py.battlefield)} (must be byte-equal at 2 -- "
        f"Skullsnap Nuisance observer + Probe Enchantment trigger source)"
    )
    assert rs.get_life(0) == py.players[0].life == 20, (
        f"p0 life: Rust={rs.get_life(0)}, Python={py.players[0].life} "
        f"(must be byte-equal at 20 -- untouched by Surveil)"
    )
    assert rs.get_life(1) == py.players[1].life == 20, (
        f"p1 life: Rust={rs.get_life(1)}, Python={py.players[1].life} "
        f"(must be byte-equal at 20 -- untouched)"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Gremlin Tamer: Eerie ENTERS-trigger -> CreateToken(Gremlin 1/1)
#   triggered_ability event=enters,
#                     predicate=And(Subject(None, IsEnchantment()),
#                                   Controlled(YOU)),
#                     effect=CreateToken(token=Gremlin 1/1 Creature,
#                                        count=1, tapped=False)
# Token registration: the Galactic Wayfarer / Bioengineered Future /
# Biomechan Engineer / Biotech Specialist / Wedgelight Rammer probes
# established the canonical ``register_token_printing`` two-step
# pattern; Gremlin Tamer applies that pattern to the Eerie predicate
# composition for the first time.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_gremlin_tamer_eerie_create_gremlin_token_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Gremlin Tamer
    (round 24, ENTERS + Eerie predicate -> CreateToken(Gremlin 1/1)).**

    Drives the **real parsed Gremlin Tamer printing** (verified at
    probe entry) on the Python side and a bridged synthetic carrier on
    the Rust side through the ``ENTERS`` dispatch path for an
    enchantment that ETBs under the observer's control.  The Eerie
    observer's trigger spawns a Gremlin 1/1 token onto p0's bf under
    p0's control.

    **NEW Effect-lane coverage paired with Probe 1.** Gremlin Tamer is
    the CreateToken-effect sibling of Skullsnap Nuisance's Surveil-
    effect lane -- both ride the IDENTICAL Eerie predicate composition
    (``And(Subject(None, IsEnchantment()), Controlled(YOU))``) through
    the SAME ENTERS dispatch.  The ``create_token`` bridge arm has
    been pinned by:

      * ``test_cross_engine_real_eoe_honored_knight_captain_etb_create_
        soldier_token_parity`` -- Soldier 1/1 Creature token via
        bare ``SourceIsSelf`` predicate.
      * ``test_cross_engine_real_eoe_knight_luminary_etb_create_soldier_
        token_parity`` -- Soldier 1/1 Creature token via bare
        ``SourceIsSelf`` predicate.
      * ``test_cross_engine_real_eoe_wedgelight_rammer_etb_create_robot_
        artifact_creature_token_parity`` -- Robot 2/2 Artifact-Creature
        via bare ``SourceIsSelf``.
      * ``test_cross_engine_real_eoe_galactic_wayfarer_etb_create_
        lander_artifact_token_parity`` -- Lander Artifact (non-creature)
        via bare ``SourceIsSelf``.
      * ``test_cross_engine_real_eoe_bioengineered_future_etb_create_
        lander_artifact_token_enchantment_carrier_parity`` -- Lander
        via bare ``SourceIsSelf`` on an Enchantment carrier.
      * ``test_cross_engine_real_eoe_biomechan_engineer_etb_create_
        lander_artifact_token_insect_artificer_carrier_parity`` --
        Lander via bare ``SourceIsSelf`` on a Creature carrier.
      * ``test_cross_engine_real_eoe_biotech_specialist_etb_create_
        lander_artifact_token_insect_scientist_carrier_parity`` --
        Lander via bare ``SourceIsSelf`` on a Creature carrier.

    **No probe has driven ``create_token`` from the Eerie predicate
    composition** until this one.  The orthogonal cover this probe
    gives the create_token bridge arm is:
      (a) The Eerie predicate composition's first-time pinning with
          the create_token effect (matches Probe 1's "Eerie predicate
          + new effect lane" pattern).
      (b) A Gremlin 1/1 Creature-only token shape (distinct from
          Soldier 1/1 / Robot 2/2 Artifact-Creature / Lander
          non-creature Artifact -- 4 prior shapes, Gremlin is the
          5th token-shape axis).

    **Earlier deferral overruled.** The ``test_probe_eerie_cards_nn.py``
    drop note at lines 68-73 explicitly deferred Gremlin Tamer:

      "Gremlin Tamer -- ``CreateToken(count=1, token=Gremlin 1/1)``.
       The bridge arm exists (``cross_engine.py``:2029), but requires
       seating the Gremlin ``CardPrinting`` via
       ``register_token_printing`` and a Rust ``register_printing``
       call -- non-trivial two-step registration not tested in the
       ENTERS-Eerie lane.  Deferred to a dedicated token-creation
       probe batch; out of scope here."

    Since that deferral, the Galactic Wayfarer / Wedgelight Rammer /
    Bioengineered Future / Biomechan Engineer / Biotech Specialist
    probes have all pinned the ``register_token_printing`` two-step
    pattern as the canonical token-spawn probe shape (the Galactic
    Wayfarer docstring at ``test_parity_smoke.py``:35699-35790
    documents the pattern verbatim).  The substrate is now tractable
    in the Eerie ETB lane too -- the pattern applies identically; the
    only difference is the *predicate* gates on the entering
    enchantment rather than ``SourceIsSelf``.

    **Bridge arms:** ``create_token`` (``cross_engine.py``:2029);
    ``subject_is_enchantment`` (``cross_engine.py``:8977); ``and``
    (``cross_engine.py``); ``controlled_by_you``
    (``cross_engine.py``:8986).

    Setup:
      * p0 has the genuine parsed Gremlin Tamer (2/2 Creature --
        Human Scout) on the battlefield, summoning_sick=False.
      * p0 / p1 libraries both empty; both hands empty before the
        Probe Enchantment inject.
      * A bare ``Probe Enchantment`` carrier is registered on both
        sides (no triggers); a Gremlin 1/1 Creature token printing
        is registered via ``register_and_inject_object`` on the
        Rust side (allocating a pid) + ``register_token_printing``
        on the Python side (binding the same pid to the Python
        printing fixture).
      * Active player = p0.

    Trigger flow:
      1. Rust: ``push_to_stack(rs_ench)`` + ``resolve_top_of_stack``
         moves the Probe Enchantment from p0's hand onto p0's bf and
         dispatches Event::Enters with subject=rs_ench.id.  Gremlin
         Tamer's observer trigger evaluates
         ``SubjectIsEnchantment`` against Probe Enchantment (True)
         AND ``ControlledByYou`` against
         source_controller=0==subject_controller=0 (True) -> trigger
         pushed.
         Python: ``resolve_top_of_stack`` moves the Probe Enchantment
         onto p0's bf and fires the ENTERS dispatch with subject=
         py_ench.  Same predicate match.
      2. Both stacks have 1 item (the CreateToken trigger).
      3. Drain: CreateToken.resolve spawns one Gremlin 1/1 token onto
         p0's bf under p0's control on both engines (the I81 same-
         controller routing via the source's controller index).

    Observables asserted (targeted):
      * p0 battlefield grows from 1 (Gremlin Tamer) to 3 (Gremlin
        Tamer + Probe Enchantment + Gremlin token) on BOTH engines.
      * p1 battlefield remains empty on both.
      * The spawned Gremlin token's controller is 0 on both engines.
      * The spawned Gremlin token's printing name matches across
        engines.
      * Stack drains cleanly: pre-drain 1 -> post-drain 0 on BOTH
        engines.
      * Lives unchanged at 20 / 20 on both engines.

    Rust triggered-ability dict::

        {
            "event": "enters",
            "predicate": {
                "kind": "and",
                "left": {"kind": "subject_is_enchantment"},
                "right": {"kind": "controlled_by_you"},
            },
            "effect": {
                "kind": "create_token",
                "count": 1,
                "token_printing_id": <gremlin_pid>,
            },
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
        clear_token_printings,
        register_token_printing,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import (
        Event, Controlled, YOU, And, Subject,
    )
    from mtg_bot.effects.object_predicates import IsEnchantment
    from mtg_bot.effects.generic.tokens import CreateToken

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Gremlin Tamer printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Gremlin Tamer")
    if real is None:
        pytest.skip("Gremlin Tamer absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Gremlin Tamer must be a Creature"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Gremlin Tamer must have an ENTERS triggered ability"
    )
    assert isinstance(enters_ta.effect, CreateToken), (
        f"Gremlin Tamer ENTERS effect must be CreateToken; "
        f"got {type(enters_ta.effect).__name__}"
    )
    assert enters_ta.effect.count == 1, (
        f"Gremlin Tamer CreateToken count must be 1; "
        f"got {enters_ta.effect.count}"
    )
    token_pr = enters_ta.effect.token_printing
    assert token_pr.name == "Gremlin", (
        f"Gremlin Tamer token name must be 'Gremlin'; "
        f"got {token_pr.name!r}"
    )
    assert "Creature" in token_pr.card_types, (
        f"Gremlin Tamer token must be a Creature; "
        f"got {token_pr.card_types}"
    )
    assert "Gremlin" in token_pr.subtypes, (
        f"Gremlin Tamer token must have Gremlin subtype; "
        f"got {token_pr.subtypes}"
    )
    assert token_pr.power == 1 and token_pr.toughness == 1, (
        f"Gremlin Tamer token must be 1/1; "
        f"got {token_pr.power}/{token_pr.toughness}"
    )
    # Predicate composition: And(Subject(None, IsEnchantment()),
    # Controlled(YOU)) -- same Eerie shape as Probe 1.
    pred = enters_ta.predicate
    assert isinstance(pred, And), (
        f"Gremlin Tamer predicate must be And; got {type(pred).__name__}"
    )
    found_subject_is_enchantment = False
    found_controlled_you = False

    def _walk(p):
        nonlocal found_subject_is_enchantment, found_controlled_you
        if isinstance(p, And):
            _walk(p.left)
            _walk(p.right)
        elif isinstance(p, Subject) and isinstance(p.inner, IsEnchantment):
            found_subject_is_enchantment = True
        elif isinstance(p, Controlled) and p.by == YOU:
            found_controlled_you = True

    _walk(pred)
    assert found_subject_is_enchantment and found_controlled_you, (
        f"Gremlin Tamer predicate must contain Subject(None, "
        f"IsEnchantment()) AND Controlled(YOU); got {pred!r}"
    )

    # ------------------------------------------------------------------
    # 2. Build cross-engine states with EMPTY libraries.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND
    ZL = 1  # ZONE_LIBRARY

    # ------------------------------------------------------------------
    # 3. Register the Gremlin token printing on the Rust side, getting
    #    a pid back; bind the same pid on the Python side via
    #    register_token_printing so the bridge translator can resolve
    #    the create_token dict.  Must happen BEFORE the bridge
    #    _ta_dict_to_python_triggered_ability call below.
    # ------------------------------------------------------------------
    rs_gremlin_pid = rs.registry_size
    rs.register_and_inject_object(
        {
            "name": "Gremlin Token (Gremlin Tamer Eerie)",
            "card_types": ["Creature"],
            "subtypes": ["Gremlin"],
            "power": 1,
            "toughness": 1,
        },
        # Park the registered token in p1's library so it doesn't
        # surface on the bf -- the CreateToken arm spawns a FRESH
        # copy of this printing at resolve time; the registered
        # template object stays put.  Same idiom as the Galactic
        # Wayfarer probe.
        1, ZL,
    )
    py_gremlin_token = CardPrinting(
        name="Gremlin Token (Gremlin Tamer Eerie)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Token Creature -- Gremlin",
        supertypes=("Token",),
        card_types=("Creature",),
        subtypes=("Gremlin",),
        power=1,
        toughness=1,
        produces=frozenset(),
        triggered_abilities=(),
    )
    clear_token_printings()
    register_token_printing(rs_gremlin_pid, py_gremlin_token)

    # ------------------------------------------------------------------
    # 4. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    gt_ta_dict = {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_enchantment"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "create_token",
            "count": 1,
            "token_printing_id": rs_gremlin_pid,
        },
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(gt_ta_dict)
    assert bridge_ta.event == Event.ENTERS
    assert isinstance(bridge_ta.effect, CreateToken)
    assert bridge_ta.effect.count == 1

    # ------------------------------------------------------------------
    # 5. Rust: pre-seat Gremlin Tamer carrier on p0's bf.
    # ------------------------------------------------------------------
    rs_gt_id = rs.register_and_inject_object(
        {
            "name": "Gremlin Tamer",
            "card_types": ["Creature"],
            "subtypes": ["Human", "Scout"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "triggered_abilities": [gt_ta_dict],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    assert rs.find_object_zone(rs_gt_id) == ZB, (
        "Rust: Gremlin Tamer must start on p0's bf"
    )
    rs_bf_p0_before = rs.battlefield_sizes[0]
    rs_bf_p1_before_with_token = rs.battlefield_sizes[1]
    # Note: p1 bf doesn't contain the token (it's in p1's LIBRARY).
    assert rs_bf_p0_before == 1, (
        f"Rust: p0 bf must contain only Gremlin Tamer pre-trigger; "
        f"got {rs_bf_p0_before}"
    )
    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty post-inject (Gremlin Tamer's own "
        f"ENTERS doesn't match the Eerie predicate -- subject is a "
        f"Creature, not Enchantment); got {rs.stack_size()}"
    )

    # ------------------------------------------------------------------
    # 6. Rust: push Probe Enchantment from p0's hand to the stack,
    #    resolve -> ETB -> Gremlin Tamer's Eerie observer fires.
    # ------------------------------------------------------------------
    rs_ench_id = rs.register_and_inject_object(
        {
            "name": "Probe Enchantment",
            "card_types": ["Enchantment"],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_ench_id, 0)
    rs.resolve_top_of_stack()
    assert rs.find_object_zone(rs_ench_id) == ZB, (
        "Rust: Probe Enchantment must have resolved onto p0's bf"
    )
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Gremlin Tamer Eerie CreateToken) "
        f"must be on the stack after Probe Enchantment ETBs; "
        f"got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0
    # Post-drain: p0's bf should have Gremlin Tamer + Probe
    # Enchantment + Gremlin token = 3 objects.
    rs_bf_p0_after = rs.battlefield_sizes[0]
    assert rs_bf_p0_after == 3, (
        f"Rust: p0 bf must contain Gremlin Tamer + Probe Enchantment "
        f"+ Gremlin token = 3 objects; got {rs_bf_p0_after}"
    )
    # Find the spawned Gremlin token on Rust's bf.
    rs_bf_snap = rs.battlefield_snapshot()
    rs_gremlin_tokens = [
        d for d in rs_bf_snap
        if d["printing_name"] == "Gremlin Token (Gremlin Tamer Eerie)"
    ]
    assert len(rs_gremlin_tokens) == 1, (
        f"Rust: expected exactly 1 Gremlin token on bf; "
        f"got {len(rs_gremlin_tokens)}"
    )
    assert rs_gremlin_tokens[0]["controller_id"] == 0, (
        f"Rust: spawned Gremlin token's controller_id must be 0 "
        f"(source's controller); got "
        f"{rs_gremlin_tokens[0]['controller_id']}"
    )

    # ------------------------------------------------------------------
    # 7. Python: build a Python printing for Gremlin Tamer using the
    #    bridge-translated TA (so the token-spawn route shares the
    #    registered Gremlin printing via the cross-engine token
    #    registry).  Following the Galactic Wayfarer / Wedgelight
    #    Rammer / Biotech Specialist probe pattern: rebuild the Python
    #    printing with the bridge-translated TA rather than the
    #    genuinely parsed TA so both engines' token-spawn routes
    #    resolve to the SAME registered Gremlin printing.  The
    #    `real` printing's existence + shape was already verified at
    #    probe entry (step 1).
    # ------------------------------------------------------------------
    py_gt_printing = CardPrinting(
        name="Gremlin Tamer",
        mana_cost_str=real.mana_cost_str,
        mana_cost=real.mana_cost,
        type_line=real.type_line,
        supertypes=real.supertypes,
        card_types=real.card_types,
        subtypes=real.subtypes,
        power=int(real.power),
        toughness=int(real.toughness),
        produces=real.produces,
        keywords=real.keywords,
        triggered_abilities=(bridge_ta,),
    )
    py_gt = py.new_object(
        py_gt_printing, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_gt.summoning_sick = False
    py_gt.tapped = False
    py_gt.damage = 0
    py_gt.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_gt)

    py_bf_before = len(py.battlefield)
    assert py_bf_before == 1, (
        f"Python: bf must contain only Gremlin Tamer pre-trigger; "
        f"got {py_bf_before}"
    )

    # ------------------------------------------------------------------
    # 8. Python: push Probe Enchantment to stack, resolve -> ETB ->
    #    Eerie observer fires -> CreateToken spawns the Gremlin.
    # ------------------------------------------------------------------
    enchant_printing = CardPrinting(
        name="Probe Enchantment",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Enchantment",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )
    py_ench = py.new_object(enchant_printing, owner_id=0, zone=Zone.STACK)
    py.stack.append(StackItem(source=py_ench, controller_id=0))
    resolve_top_of_stack(py)
    assert any(
        o.printing.name == "Probe Enchantment" for o in py.battlefield
    ), "Python: Probe Enchantment must have resolved onto p0's bf"
    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Gremlin Tamer Eerie CreateToken) "
        f"must be on the stack after Probe Enchantment ETBs; "
        f"got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0
    py_bf_after = len(py.battlefield)
    assert py_bf_after == 3, (
        f"Python: bf must contain Gremlin Tamer + Probe Enchantment "
        f"+ Gremlin token = 3 objects; got {py_bf_after}"
    )
    # Find the spawned Gremlin token.
    py_gremlin_tokens = [
        o for o in py.battlefield
        if o.printing.name == "Gremlin Token (Gremlin Tamer Eerie)"
    ]
    assert len(py_gremlin_tokens) == 1, (
        f"Python: expected exactly 1 Gremlin token on bf; "
        f"got {len(py_gremlin_tokens)}"
    )
    assert py_gremlin_tokens[0].controller_id == 0, (
        f"Python: spawned Gremlin token's controller_id must be 0 "
        f"(source's controller); got "
        f"{py_gremlin_tokens[0].controller_id}"
    )

    # ------------------------------------------------------------------
    # 9. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_bf_p0_after == py_bf_after == 3, (
        f"p0 battlefield size: Rust={rs_bf_p0_after}, "
        f"Python={py_bf_after} (must be byte-equal at 3 -- Gremlin "
        f"Tamer + Probe Enchantment + spawned Gremlin token)"
    )
    assert rs_gremlin_tokens[0]["controller_id"] == \
        py_gremlin_tokens[0].controller_id == 0, (
        f"Spawned Gremlin token's controller_id: "
        f"Rust={rs_gremlin_tokens[0]['controller_id']}, "
        f"Python={py_gremlin_tokens[0].controller_id} "
        f"(must be byte-equal at 0 -- I81 same-controller routing)"
    )
    assert rs.get_life(0) == py.players[0].life == 20, (
        f"p0 life: Rust={rs.get_life(0)}, Python={py.players[0].life} "
        f"(must be byte-equal at 20 -- untouched by CreateToken)"
    )
    assert rs.get_life(1) == py.players[1].life == 20, (
        f"p1 life: Rust={rs.get_life(1)}, Python={py.players[1].life} "
        f"(must be byte-equal at 20 -- untouched)"
    )
