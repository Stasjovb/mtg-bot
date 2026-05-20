"""Divergence-pin tests: batch VVV (round 24 pin-side).

Round 24 pin batch surfacing the high-confidence divergence-pin
candidates the UUU probe agent dropped during honest exhaustion
(see ``tests/test_probe_remaining_uuu.py`` at commit ``bd67d65f``),
plus two fresh BLOCKED-list candidates from
``docs/POOL_PARITY.md::BLOCKED -- genuinely_missing``.

Each pin test is named ``test_..._divergence_pin`` and ASSERTS the
CURRENT divergent behavior rather than parity.  The PROBED-tier
detector excludes ``*_divergence_pin`` functions, so these tests
grow the test surface without touching the PROBED metric.

Pin closure cadence: when a sibling Rust slice closes the
underlying gap, the relevant assertion fires and the pin is
renamed ``*_FIXED_parity`` with the sentinel inverted (PPP / MMM /
JJJ / RRR / TTT Pin 1 precedent).

Pinned bugs
-----------

Pin 1 -- Rust ``Predicate::SourceIsSelf`` at
``rust/src/cards.rs:4730`` is the strict ``source_id == subject_id``
identity check.  Phase-step events (BEGINNING_OF_POSTCOMBAT_MAIN
closed by slice 10 + the PPP Pin 3 round-21 ``Source(IsTapped)``
closure) dispatch with ``PLAYER_SUBJECT_OFFSET + active_player`` as
``subject_id`` -- a sentinel marking a player-subject event rather
than a permanent-subject one.  Because the sentinel value is large
(``0x8000_0000`` + small player index) and the firing source's
``id`` is a small permanent id, ``source_id == subject_id`` is
ALWAYS false for these phase-step dispatches, and the Survivor-
family postcombat-main trigger silently never pushes on Rust.

Python's ``IsSelf.matches`` at ``src/mtg_bot/effects/predicates.py``
:428-436 carries an explicit player-subject tautology arm: if
``self.subject is None and obj is not None and not hasattr(obj,
"printing")`` then return True.  Players expose ``id`` but no
``printing`` attribute, so on a player-subject event Python's
``IsSelf()`` reads as "source IS itself" and evaluates True --
matching the CR-canonical reading: the dispatcher already iterates
one source at a time, so the predicate is structurally tautological
for player-subject events.

  Bug location (Rust -- needs the fix):
    ``rust/src/cards.rs:4730`` -- the ``Predicate::SourceIsSelf``
    arm of ``Predicate::matches``::

        Predicate::SourceIsSelf => source_id == subject_id,

    Strict equality with no player-subject sentinel arm.  Compare
    with the immediately-following ``ControlledByYou`` arm at
    ``cards.rs:4758-4807`` which DOES carry a
    ``PLAYER_SUBJECT_OFFSET`` recognising branch (the round-14
    phase-step events closure pattern); SourceIsSelf is the only
    predicate-family member where the player-subject tautology
    is missing.

  Bug location (Python -- the correct behavior the Rust arm should
  match):
    ``src/mtg_bot/effects/predicates.py:428-436`` --
    ``IsSelf.matches``::

        def matches(self, state, subjects, source):
            obj = _resolve_subject(subjects, self.subject)
            if (
                self.subject is None
                and obj is not None
                and not hasattr(obj, "printing")
            ):
                return True
            return obj is source

    The ``not hasattr(obj, "printing")`` check is the player-subject
    tautology arm: Players have ``id`` but no ``printing``, so the
    predicate falls through to True on a player-subject event.

  Sibling pattern (ControlledByYou's PLAYER_SUBJECT_OFFSET arm):
    The same predicate-evaluator function ALREADY recognises the
    ``PLAYER_SUBJECT_OFFSET`` sentinel in its ``ControlledByYou``
    + ``ControlledByOpponent`` arms (``cards.rs:4778-4807`` +
    ``cards.rs:4820-4853``).  SourceIsSelf needs an isomorphic
    sentinel-recognising arm.

  Scale (EoE cards affected): 5 direct -- ALL EoE "Survivor" cards
  with the postcombat-main triggered ability that the PPP Pin 3 +
  round-21 ``Source(IsTapped)`` RR closure listed as "unlocked":
    * Savior of the Small
    * Cautious Survivor
    * Defiant Survivor
    * House Cartographer
    * Shrewd Storyteller
  All 5 print with an
  ``And(And(ControlledByYou, IsSelf()), SourceIsTapped())`` predicate
  on the BEGINNING_OF_POSTCOMBAT_MAIN event lane; the IsSelf clause
  silently fails on Rust, so even though the ETB event dispatches
  correctly + the ``ControlledByYou`` + ``SourceIsTapped`` clauses
  evaluate True, the composite predicate gates False and the trigger
  never pushes.  The PPP "unlocked" notes at
  ``rust/src/state_ops_steps.rs:632-634`` + ``rust/src/cards.rs:4474``
  -4475 are technically correct at the EVENT-dispatch + PREDICATE-
  PARSE layer but PREMATURE on the end-to-end byte-equal layer --
  the IsSelf evaluator gap had not been surfaced until the UUU
  probe agent's honest-exhaustion run.

  Closure path:
    1. Locate the ``Predicate::SourceIsSelf`` arm at
       ``rust/src/cards.rs:4730``.
    2. Replace the bare ``source_id == subject_id`` with a sentinel-
       aware branch that mirrors the ``ControlledByYou`` arm at
       :4776-4807 -- when ``subject_id >= PLAYER_SUBJECT_OFFSET``,
       the predicate has no meaningful "self" comparison (the
       subject is a Player, not a permanent) and should fall back
       to ``true`` (the tautological-on-player-subject reading
       Python's ``not hasattr(obj, "printing")`` arm implements)::

           Predicate::SourceIsSelf => {
               if subject_id >= PLAYER_SUBJECT_OFFSET {
                   // Phase-step / player-subject events: the
                   // dispatcher iterates one source at a time, so
                   // IsSelf is structurally tautological. Mirrors
                   // Python IsSelf.matches's
                   // ``not hasattr(obj, "printing")`` arm at
                   // src/mtg_bot/effects/predicates.py:432-435.
                   true
               } else {
                   source_id == subject_id
               }
           }
    3. The UUU probe agent's drop note (test_probe_remaining_uuu.py
       :119-132) calls out an alternative (b): change the bridge's
       ``source_is_self`` translation for player-subject events to
       ``always``.  The Rust-side fix (a) above is preferred --
       it's the CR-canonical fix at the engine layer, doesn't touch
       the bridge's parse contract, and centralizes the sentinel
       handling next to its sibling ``ControlledByYou`` arm.
    4. Flip this pin's assertion (the bare ``source_id ==
       subject_id`` should NO LONGER appear in the ``SourceIsSelf``
       arm; a sentinel branch should appear in its place) and
       rename ``..._divergence_pin`` -> ``..._FIXED_parity`` per
       the PPP / MMM / TTT closure-cadence precedent.

Pin 2 -- Command Bridge ETB's ``SacrificeSelfUnlessTapPermanent``
effect has no Rust ``Effect`` variant.  Python implements via the
``SacrificeSelfUnlessTapPermanent`` Effect class in
``src/mtg_bot/effects/combinators.py:96-168``; Rust has no matching
Effect arm, no parse arm, and no resolve arm.  This is one of 7
cards on the ``docs/POOL_PARITY.md`` BLOCKED-genuinely_missing list
(per the round-58 N2 worklist) and the canonical example of the
"land-ETB trigger path + tap-a-permanent cost decision" subsystem
gap (24522 17lands decks per ``docs/RESIDUE_CARD_PLANS.md``:82 --
the second-highest decked card on the residue worklist).

  Bug location (Python -- the canonical behavior the Rust side
  should match):
    ``src/mtg_bot/effects/combinators.py:96-168`` -- the
    ``SacrificeSelfUnlessTapPermanent`` Effect class.  ETB-time
    "sacrifice this unless you tap an untapped permanent you
    control" rider, reads ``state.resolving_source``, builds the
    legal "alternative-cost" pick set, dispatches a ``choose_target``
    with kind ``"untapped_permanent"`` if the set is non-empty,
    sacrifices the source otherwise.

  Bug location (Rust -- the gap):
    ``rust/src/cards.rs::Effect`` enum -- NO arm matching this
    shape.  Confirmed via grep: zero hits for
    ``SacrificeSelfUnlessTapPermanent`` / ``sacrifice_self_unless_
    tap`` / ``command_bridge`` / ``CommandBridge`` across the Rust
    crate (``rust/src/*.rs``).

  Scale (EoE cards affected): 1 direct (Command Bridge -- the only
  EoE printing using this exact ETB-rider shape).  Deferred-
  subsystem-blocked: closing this end-to-end requires (a) the new
  Effect arm, (b) the land-ETB event-dispatch contract for an
  enters-tapped land (Rust's land-ETB path already sets
  ``enters_tapped`` but doesn't fire ETB triggers on the same dispatch
  the spell-resolve ETB lane uses), AND (c) a tap-a-permanent cost-
  style choose-target decision pump that mirrors Python's
  ``choose_target`` with kind ``"untapped_permanent"``.

  Closure path:
    1. Add ``Effect::SacrificeSelfUnlessTapPermanent`` unit variant
       to the ``rust/src/cards.rs::Effect`` enum (zero-field; the
       source-and-controller are read from
       ``state.resolving_source`` at resolve time, mirroring the
       Python convention).
    2. Add parse arm in ``rust/src/cards.rs::parse_effect`` for the
       ``"sacrifice_self_unless_tap_permanent"`` effect_kind string
       (and matching ``effect_to_pydict`` arm).
    3. Add the resolve arm in ``rust/src/state_ops_resolve.rs``:
         a. Read the source from ``state.resolving_source``; bail
            silently if absent.
         b. Build the candidate set: untapped permanents controlled
            by the source's controller, EXCLUDING the source itself
            (the source might be Command Bridge entering tapped, so
            the source-exclusion is load-bearing).
         c. If candidates is empty -> directly sacrifice the source
            (the no-choice path).
         d. Otherwise queue a ``PendingDecision::TapPermanentChoice``
            (mirror of the ``SurveilChoice`` shape) that resolves
            to either a permanent id (tap that permanent + keep
            the source) or a decline sentinel (sacrifice the source).
    4. Add bridge arm in ``src/mtg_bot/parity/cross_engine.py::
       _ta_dict_to_python_effect`` mapping the
       ``"sacrifice_self_unless_tap_permanent"`` effect_kind string
       to ``SacrificeSelfUnlessTapPermanent()``.
    5. Wire the land-ETB dispatch path so Command Bridge's ENTERS
       trigger fires when the land enters tapped (Rust's
       ``Effect::Land`` resolve currently routes the source to bf
       + sets ``tapped=true`` but doesn't fan out ETB triggers from
       the land-ETB lane -- the spell-resolve ETB-trigger fan-out
       at ``state_ops_resolve.rs::move_source_post_resolve`` is the
       sibling pattern to mirror).
    6. Add a real-EoE byte-equal probe for Command Bridge that
       drives ENTERS -> SacrificeSelfUnlessTapPermanent via the
       live registry, then flip this pin to ``..._FIXED_parity``
       per the standard cadence.

Pin 3 -- Pain for All's ETB body parses to bespoke
``PainForAllETBEffect`` on the Python side
(``src/mtg_bot/effects/bespoke.py:352-432``) plus the sibling
``PainForAllDamageEchoEffect`` damage-echo trigger
(``bespoke.py:433-467``); Rust's ``Effect`` enum has no matching
variants.  This is the canonical example of the "Aura-attachment
+ damage-feedback subsystem" gap on the BLOCKED-genuinely_missing
list (4367 17lands decks per ``docs/RESIDUE_CARD_PLANS.md``:95).

  Bug location (Python -- the canonical behavior):
    ``src/mtg_bot/effects/bespoke.py:352-432`` --
    ``PainForAllETBEffect``: ETB-time damage to enchanted creature's
    controller's permanents based on enchanted creature's power.
    Sibling damage-echo at ``bespoke.py:433-467``
    (``PainForAllDamageEchoEffect``) carries the
    ``Whenever enchanted creature deals damage...`` repeating-damage
    rider.  Both Effect classes read the aura's ``attached_to``
    pointer to find the enchanted creature.

  Bug location (Rust -- the gap):
    ``rust/src/cards.rs::Effect`` enum -- NO arm matching either
    shape.  Confirmed via grep: zero hits for ``PainForAll`` /
    ``pain_for_all`` / ``EnchantedDealsDamageThenPropagate``
    across the Rust crate (``rust/src/*.rs``).

  Scale (EoE cards affected): 1 direct (Pain for All -- the unique
  Aura with this damage-echo propagation rider).  Deferred-subsystem-
  blocked: closing this end-to-end requires (a) Aura ``attached_to``
  routed end-to-end (per ``rust/src/cards.rs:1240`` deferred note
  and ``docs/SEARCH_LIMITATIONS.md`` Aura-attachment row), AND (b)
  a damage-feedback / self-replicating-damage substrate (the echo
  trigger fires whenever the enchanted creature deals damage, which
  may itself fire the echo again via further triggered damage --
  the loop guard is non-trivial).  The Aura-attachment subsystem is
  the leverage axis here: closing it unblocks Pain for All,
  Meltstrider's Resolve, AND Tractor Beam (all 3 listed under the
  Aura ``attached_to`` end-to-end bucket on
  ``docs/RESIDUE_CARD_PLANS.md``:107-110).

  Closure path:
    1. Add Aura ``attached_to`` end-to-end routing to Rust per
       ``rust/src/cards.rs:1240`` deferred note (the
       ``docs/SUBSYSTEM_ROADMAP.md`` Aura-attachment subsystem --
       multi-round closure scope).
    2. Add ``Effect::PainForAllETBEffect`` (zero-field unit
       variant; reads source via ``state.resolving_source`` ->
       ``attached_to`` -> enchanted-creature controller).
    3. Add ``Effect::PainForAllDamageEchoEffect`` for the damage-
       feedback echo trigger; the loop guard ("an echo of
       damage-from-the-echo doesn't infinitely propagate") needs a
       per-game ledger flag or a CR-canonical "this turn"
       triggered-ability scope.
    4. Add parse arms + resolve arms + bridge arms following the
       TTT Pin 3 / SSS bespoke-Effect closure pattern.
    5. Add real-EoE byte-equal probes for Pain for All (ETB damage
       lane + damage-echo lane) and flip this pin to
       ``..._FIXED_parity`` per the standard cadence.

This batch is a coherent set of three high-confidence pins surfaced
from the UUU probe agent's honest-exhaustion drops (Pin 1) plus
two fresh BLOCKED-list candidates from the genuinely_missing 7-card
list (Pins 2 + 3).  All three pins sit on the same axis: the
Python<->Rust resolve-path alignment that the round-24 cycle is
narrowing.  No two pins share a closure surface: Pin 1 closes at
the predicate-evaluator layer (sentinel-aware ``SourceIsSelf``);
Pin 2 closes at the Effect-arm + land-ETB-dispatch + cost-decision-
pump layer (multi-round Aura-orthogonal); Pin 3 closes at the Aura-
attachment substrate + damage-feedback layer (multi-round subsystem
gate covering 3 cards including Pain for All).
"""

from __future__ import annotations

import inspect
import pathlib

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- Rust Predicate::SourceIsSelf missing player-subject tautology
#          arm at cards.rs:4730.  Strict source_id == subject_id check
#          always evaluates False on phase-step events (which dispatch
#          with PLAYER_SUBJECT_OFFSET + active_player as subject_id).
#          5 EoE cards affected: Savior of the Small, Cautious
#          Survivor, Defiant Survivor, House Cartographer, Shrewd
#          Storyteller (the EoE Survivor postcombat-main family).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_survivor_family_source_is_self_player_subject_FIXED_parity():
    """FIXED-parity (VVV Pin 1 closed 2026-05-20, 15th Rust slice).

    The ``Predicate::SourceIsSelf`` arm of ``Predicate::matches`` at
    ``rust/src/cards.rs`` previously was the bare
    ``source_id == subject_id`` identity check.  Phase-step events
    dispatch with ``PLAYER_SUBJECT_OFFSET + active_player`` as
    ``subject_id``, so ``SourceIsSelf`` always evaluated False for
    those events.  Python's ``IsSelf.matches`` at
    ``src/mtg_bot/effects/predicates.py:428-436`` carries a
    player-subject tautology arm (``not hasattr(obj, "printing")``)
    that evaluates True for player subjects.  The 15th Rust slice
    mirrored the sibling ``ControlledByYou`` arm's
    PLAYER_SUBJECT_OFFSET-recognising branch in the
    ``Predicate::SourceIsSelf`` arm so player-subject events
    structurally evaluate True (the dispatcher already iterates one
    source at a time, so IsSelf is tautological for player subjects).

    FIXED-parity shape (inverted from the original divergence pin):
      1. Python's ``IsSelf.matches`` still carries the player-subject
         tautology arm (canonical behavior unchanged).
      2. Sentinel A (inverted): the bare
         ``Predicate::SourceIsSelf => source_id == subject_id,``
         expression is NO LONGER present in cards.rs — the arm now
         carries a PLAYER_SUBJECT_OFFSET-aware branch.
      3. Sentinel B (preserved): the sibling
         ``Predicate::ControlledByYou`` arm continues to carry its
         PLAYER_SUBJECT_OFFSET-recognising branch (the mirror target).
      4. Sentinel C (new): the ``Predicate::SourceIsSelf`` arm itself
         contains the ``subject_id >= PLAYER_SUBJECT_OFFSET`` branch
         and cites the VVV Pin 1 closure marker.
      5. Confirm all 5 affected EoE Survivor cards are loadable AND
         carry a postcombat-main triggered ability with an ``IsSelf``
         clause in the predicate composition (unchanged).

    EoE card scale unblocked: 5 (Savior of the Small, Cautious
    Survivor, Defiant Survivor, House Cartographer, Shrewd
    Storyteller).
    """
    # 1. Python's IsSelf.matches carries the player-subject tautology arm.
    from mtg_bot.effects.predicates import IsSelf, Event
    is_self_src = inspect.getsource(IsSelf.matches)
    assert 'not hasattr(obj, "printing")' in is_self_src, (
        "FIXED-parity invariant: Python's IsSelf.matches at "
        "src/mtg_bot/effects/predicates.py should still contain the "
        "player-subject tautology arm 'not hasattr(obj, \"printing\")' "
        "— this is the canonical behavior Rust mirrors.  If absent, "
        "the Python side changed convention — audit + update this "
        f"test.  Source:\n{is_self_src!r}"
    )
    assert "return True" in is_self_src, (
        "FIXED-parity invariant: Python's IsSelf.matches should "
        "return True from the player-subject tautology arm."
    )

    # 1a. Event.BEGINNING_OF_POSTCOMBAT_MAIN is the canonical dispatch
    #     lane enum the Survivor cards consume.
    assert hasattr(Event, "BEGINNING_OF_POSTCOMBAT_MAIN"), (
        "FIXED-parity invariant: Event enum should expose "
        "BEGINNING_OF_POSTCOMBAT_MAIN (the round-21 PPP Pin 3 + "
        "slice-10 closure)."
    )

    # 2. Locate the Rust cards.rs source file.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]  # tests/.. = repo root
    rust_cards_path = repo_root / "rust" / "src" / "cards.rs"
    assert rust_cards_path.exists(), (
        f"Rust source file should exist at {rust_cards_path!r}."
    )
    rust_src = rust_cards_path.read_text(encoding="utf-8")

    # 2a. Locate the Predicate::matches function body.
    matches_sig = "Predicate::Always => true,"
    matches_start = rust_src.find(matches_sig)
    assert matches_start >= 0, (
        f"Rust source should contain the Predicate::matches arm "
        f"signature {matches_sig!r}."
    )
    matches_body = rust_src[matches_start:matches_start + 20000]

    # 2b. Sentinel A (INVERTED): the bare
    #     ``Predicate::SourceIsSelf => source_id == subject_id,``
    #     line should NO LONGER appear.  The closure replaced the
    #     bare arm with a sentinel-aware branch.
    bare_arm = "Predicate::SourceIsSelf => source_id == subject_id,"
    assert bare_arm not in matches_body, (
        "FIXED-parity (inverted): rust/src/cards.rs should NO "
        f"LONGER contain the bare arm body {bare_arm!r}.  If "
        "present, the VVV Pin 1 closure was reverted — restore "
        "the player-subject tautology branch."
    )

    # 2c. Sentinel B (preserved): the sibling ControlledByYou arm
    #     continues to carry the PLAYER_SUBJECT_OFFSET branch.
    controlled_by_you_marker = (
        "Predicate::ControlledByYou { slot: _ } => {"
    )
    assert controlled_by_you_marker in matches_body, (
        f"FIXED-parity invariant: rust/src/cards.rs's "
        f"Predicate::matches should still contain the sibling "
        f"ControlledByYou arm marker {controlled_by_you_marker!r} "
        "(the mirrored closure pattern)."
    )

    # 2d. Sentinel C (new — closure landing): the SourceIsSelf arm
    #     itself now contains the PLAYER_SUBJECT_OFFSET-aware branch.
    #     Anchor on the arm head + the sentinel comparison.
    source_is_self_idx = matches_body.find("Predicate::SourceIsSelf =>")
    assert source_is_self_idx >= 0, (
        "FIXED-parity invariant: rust/src/cards.rs should still "
        "contain a 'Predicate::SourceIsSelf =>' arm head."
    )
    # Walk ~800 chars from the arm head to the end of the arm body
    # (the new arm is ~600 chars; ControlledByYou starts ~800 chars
    # later).
    source_is_self_arm = matches_body[
        source_is_self_idx : source_is_self_idx + 1500
    ]
    assert "subject_id >= PLAYER_SUBJECT_OFFSET" in source_is_self_arm, (
        "FIXED-parity (new closure landing): the "
        "Predicate::SourceIsSelf arm should now contain a "
        "'subject_id >= PLAYER_SUBJECT_OFFSET' branch mirroring "
        "the ControlledByYou arm's sentinel handling.  If absent, "
        "the VVV Pin 1 closure was reverted.  Arm excerpt:\n"
        f"{source_is_self_arm[:500]!r}"
    )
    assert "VVV Pin 1" in source_is_self_arm, (
        "FIXED-parity (closure citation): the "
        "Predicate::SourceIsSelf arm should cite the VVV Pin 1 "
        "closure marker in a code comment so future readers can "
        "trace the change."
    )
    # The bare equality body is now nested inside the else branch.
    assert "source_id == subject_id" in source_is_self_arm, (
        "FIXED-parity invariant: the non-player-subject path of "
        "the closed arm should still compare 'source_id == "
        "subject_id' (the strict identity reading for permanent "
        "subjects).  If absent, the closure semantics regressed."
    )

    # 3. Confirm the PLAYER_SUBJECT_OFFSET constant is declared.
    assert "pub(crate) const PLAYER_SUBJECT_OFFSET: u32" in rust_src, (
        "Pin invariant: rust/src/cards.rs should declare the "
        "PLAYER_SUBJECT_OFFSET sentinel constant (the round-14 "
        "phase-step events substrate).  If absent, the substrate "
        "moved -- update this pin's reference."
    )

    # 4. Confirm all 5 affected EoE Survivor cards are loadable AND
    #    carry the affected predicate shape.
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import And
    src = get_active_source()
    printings = src.get_printings()
    affected_eoe_cards = [
        "Savior of the Small",
        "Cautious Survivor",
        "Defiant Survivor",
        "House Cartographer",
        "Shrewd Storyteller",
    ]
    assert len(affected_eoe_cards) == 5, (
        "The Rust SourceIsSelf player-subject pin affects 5 EoE "
        "Survivor cards directly (per UUU probe agent's empirical "
        "repro at tests/test_probe_remaining_uuu.py:55-117).  "
        f"Enumerated list has {len(affected_eoe_cards)} entries."
    )

    def _walk_for_isself(pred):
        """Return True iff pred contains an IsSelf clause anywhere."""
        if isinstance(pred, IsSelf):
            return True
        if isinstance(pred, And):
            return _walk_for_isself(pred.left) or _walk_for_isself(pred.right)
        return False

    for name in affected_eoe_cards:
        pr = printings.get(name)
        assert pr is not None, (
            f"Pin invariant: {name!r} should be present in the active "
            "CardSource (the UUU probe drop note listed it among the "
            "Survivor postcombat-main family). If missing, the EoE "
            "data file was regenerated -- update this pin."
        )
        # Find the postcombat-main triggered ability.
        pcm_ta = next(
            (
                ta for ta in pr.triggered_abilities
                if ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
            ),
            None,
        )
        assert pcm_ta is not None, (
            f"Pin invariant: {name!r} should carry a "
            "BEGINNING_OF_POSTCOMBAT_MAIN triggered ability (the "
            "PPP Pin 3 / slice-10 unlock target). If absent, the "
            "parser convention changed -- update this pin."
        )
        # The predicate composition must contain an IsSelf clause
        # somewhere (the load-bearing player-subject-affected clause).
        assert _walk_for_isself(pcm_ta.predicate), (
            f"Pin invariant: {name!r}'s postcombat-main predicate "
            "should contain an IsSelf clause anywhere in the And tree "
            "(the player-subject-tautology-affected clause).  Got: "
            f"{pcm_ta.predicate!r}."
        )


# ---------------------------------------------------------------------------
# Pin 2 -- Command Bridge's SacrificeSelfUnlessTapPermanent ETB has no
#          Rust Effect variant.  Land-ETB + cost-decision-style subsystem
#          gap; one of 7 cards on docs/POOL_PARITY.md::BLOCKED --
#          genuinely_missing.  1 EoE card affected: Command Bridge.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_command_bridge_sacrifice_unless_tap_no_rust_variant_divergence_pin():
    """Pin Command Bridge's ETB effect lacking a Rust counterpart.

    Command Bridge ETBs with "sacrifice this unless you tap an untapped
    permanent you control" -- Python parses this to the
    ``SacrificeSelfUnlessTapPermanent`` Effect class at
    ``src/mtg_bot/effects/combinators.py:96-168``.  Rust's ``Effect``
    enum at ``rust/src/cards.rs`` has no matching variant -- the
    printing's ETB body cannot round-trip through the bridge.  One of
    7 cards on the ``docs/POOL_PARITY.md`` BLOCKED-genuinely_missing
    list; 24522 17lands decks per ``docs/RESIDUE_CARD_PLANS.md`` -- the
    second-highest-decked card on the residue worklist.

    Probe shape:
      1. Confirm Python's ``SacrificeSelfUnlessTapPermanent`` class
         exists with the expected interface (``resolve`` method
         present; reads ``state.resolving_source``).
      2. Sentinel: the Rust crate's source files contain NO reference
         to ``SacrificeSelfUnlessTapPermanent`` / ``sacrifice_self_
         unless_tap_permanent`` / ``CommandBridge`` /
         ``command_bridge`` -- the Rust side is silent on this effect
         today.
      3. Confirm Command Bridge is loadable + carries the expected
         ETB-trigger shape on the Python side.
      4. Confirm ``docs/POOL_PARITY.md``'s
         BLOCKED-genuinely_missing list contains Command Bridge
         (the documented worklist entry for this gap).

    Closure indicator: ``Effect::SacrificeSelfUnlessTapPermanent`` (or
    similar) lands in ``rust/src/cards.rs``, with a parse arm + resolve
    arm in ``state_ops_resolve.rs`` + bridge arm in ``cross_engine.py``.
    Pin renames to ``..._FIXED_parity`` asserting the variant + parse
    arm + resolve arm are present.

    EoE card scale: 1 directly (Command Bridge; 24522 17lands decks).
    """
    # 1. Python's SacrificeSelfUnlessTapPermanent class exists with the
    #    expected interface.
    from mtg_bot.effects.combinators import SacrificeSelfUnlessTapPermanent
    from mtg_bot.effects.base import Effect as _EffectBase

    assert issubclass(SacrificeSelfUnlessTapPermanent, _EffectBase), (
        "SacrificeSelfUnlessTapPermanent should be an Effect subclass "
        "(effects/combinators.py:96-168).  If this fails, the class "
        "was restructured -- update this pin."
    )

    inst = SacrificeSelfUnlessTapPermanent()
    assert hasattr(inst, "resolve"), (
        "SacrificeSelfUnlessTapPermanent should have a 'resolve' method "
        "(reads state.resolving_source; builds candidate set; dispatches "
        "choose_target with kind='untapped_permanent'; sacrifices the "
        "source on decline).  If absent, the convention changed."
    )

    # 1a. The resolve method reads state.resolving_source (the canonical
    #     "current resolving permanent" pointer the bespoke-effect family
    #     uses) and routes through turn.sacrifice + turn.tap_permanent.
    resolve_src = inspect.getsource(SacrificeSelfUnlessTapPermanent.resolve)
    assert "state.resolving_source" in resolve_src, (
        "SacrificeSelfUnlessTapPermanent.resolve should read "
        "state.resolving_source to find the source permanent.  If "
        "absent, the Python convention changed -- update this pin."
    )
    assert "_sacrifice" in resolve_src or "sacrifice" in resolve_src, (
        "SacrificeSelfUnlessTapPermanent.resolve should route the decline "
        "branch through turn.sacrifice.  If absent, the Python "
        "convention changed."
    )
    assert "tap_permanent" in resolve_src, (
        "SacrificeSelfUnlessTapPermanent.resolve should route the keep "
        "branch through turn.tap_permanent.  If absent, the Python "
        "convention changed."
    )

    # 2. Rust crate: NO reference to SacrificeSelfUnlessTapPermanent /
    #    sacrifice_self_unless_tap / CommandBridge / command_bridge in
    #    cards.rs or state_ops_resolve.rs.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_cards_path = repo_root / "rust" / "src" / "cards.rs"
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"

    assert rust_cards_path.exists(), (
        f"Rust source file should exist at {rust_cards_path!r}.  "
        "If the file moved, update this test's path resolution."
    )
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}."
    )

    cards_src = rust_cards_path.read_text(encoding="utf-8")
    resolve_src_rs = rust_resolve_path.read_text(encoding="utf-8")

    forbidden_substrings = [
        "SacrificeSelfUnlessTapPermanent",
        "sacrifice_self_unless_tap_permanent",
        "sacrifice_self_unless_tap",
        "CommandBridge",
        "command_bridge",
    ]
    for needle in forbidden_substrings:
        assert needle not in cards_src, (
            f"Pin sentinel: rust/src/cards.rs should NOT yet contain "
            f"{needle!r} (no Command Bridge Effect variant exists).  "
            "If this assertion fails, the closure may have landed -- "
            "audit the Rust enum + parse arm + resolve arm and flip "
            "this pin to _FIXED_parity."
        )
        assert needle not in resolve_src_rs, (
            f"Pin sentinel: rust/src/state_ops_resolve.rs should NOT "
            f"yet contain {needle!r} (no Command Bridge resolve arm "
            "exists).  If this assertion fails, the resolve arm has "
            "landed -- flip to _FIXED_parity."
        )

    # 3. Command Bridge is loadable + carries the expected ETB trigger.
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    src = get_active_source()
    pr = src.get_printings().get("Command Bridge")
    assert pr is not None, (
        "Pin invariant: 'Command Bridge' should be present in the "
        "active CardSource (per docs/POOL_PARITY.md BLOCKED-genuinely"
        "_missing list).  If missing, the EoE data file was regenerated "
        "-- update this pin."
    )
    assert "Land" in pr.card_types, (
        f"Pin invariant: Command Bridge should be a Land card type "
        f"(per the docs/RESIDUE_CARD_PLANS.md classification).  Got: "
        f"{pr.card_types}."
    )
    enters_ta = next(
        (ta for ta in pr.triggered_abilities if ta.event == Event.ENTERS),
        None,
    )
    assert enters_ta is not None, (
        "Pin invariant: Command Bridge should carry an ENTERS "
        "triggered ability (the sac-unless-tap rider).  If absent, the "
        "parser convention changed -- update this pin."
    )
    assert isinstance(enters_ta.effect, SacrificeSelfUnlessTapPermanent), (
        f"Pin invariant: Command Bridge's ENTERS effect should be "
        f"SacrificeSelfUnlessTapPermanent.  Got: "
        f"{type(enters_ta.effect).__name__}."
    )

    # 4. POOL_PARITY's BLOCKED-genuinely_missing list contains Command
    #    Bridge (the documented worklist entry for this gap).
    pool_parity_path = repo_root / "docs" / "POOL_PARITY.md"
    assert pool_parity_path.exists(), (
        f"docs/POOL_PARITY.md should exist at {pool_parity_path!r}.  "
        "If the doc moved, update this pin's reference."
    )
    pool_parity_src = pool_parity_path.read_text(encoding="utf-8")
    assert "Command Bridge" in pool_parity_src, (
        "Pin invariant: docs/POOL_PARITY.md should list 'Command "
        "Bridge' (the BLOCKED-genuinely_missing entry).  If absent, "
        "the worklist was updated -- audit this pin's BLOCKED status."
    )

    # 5. EoE cards affected.
    affected_eoe_cards = [
        "Command Bridge",
        # Land with "When this enters, sacrifice this unless you tap an
        # untapped permanent you control." 24522 17lands decks per
        # docs/RESIDUE_CARD_PLANS.md:82 (#2 decked residue card).
    ]
    assert len(affected_eoe_cards) == 1, (
        "The Command Bridge ETB-rider gap affects 1 EoE card directly.  "
        f"Enumerated list has {len(affected_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- Pain for All's PainForAllETBEffect + PainForAllDamageEcho
#          Effect Aura riders have no Rust counterpart.  Aura
#          attached_to + damage-feedback subsystem gap; one of 7 cards
#          on docs/POOL_PARITY.md::BLOCKED -- genuinely_missing.
#          1 EoE card affected: Pain for All.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_pain_for_all_aura_damage_echo_no_rust_variant_divergence_pin():
    """Pin Pain for All's ETB + damage-echo effects lacking Rust counterparts.

    Pain for All is an Aura with two triggered abilities:
      * ETB (event=ENTERS): ``PainForAllETBEffect`` (deals damage to
        each opponent based on enchanted creature's power).
      * Damage echo (event=DEALT_DAMAGE):
        ``PainForAllDamageEchoEffect`` (whenever enchanted creature
        deals damage, each opponent loses that-much life).
    Python implements both via bespoke Effect classes at
    ``src/mtg_bot/effects/bespoke.py:352-432`` (ETB) and
    ``:433-467`` (damage echo).  Rust's ``Effect`` enum has no matching
    variants -- neither shape is parseable, neither shape resolves.
    One of 7 cards on the ``docs/POOL_PARITY.md`` BLOCKED-
    genuinely_missing list; 4367 17lands decks per
    ``docs/RESIDUE_CARD_PLANS.md`` -- representative of the Aura
    ``attached_to`` end-to-end subsystem gap that ALSO blocks
    Meltstrider's Resolve + Tractor Beam (3 cards total in that
    cluster).

    Probe shape:
      1. Confirm Python's ``PainForAllETBEffect`` and
         ``PainForAllDamageEchoEffect`` classes exist with the expected
         interfaces.
      2. Sentinel: the Rust crate's source files contain NO reference
         to ``PainForAll`` / ``pain_for_all`` /
         ``EnchantedDealsDamageThenPropagate`` -- the Rust side is
         silent on both effects today.
      3. Confirm Pain for All is loadable + carries BOTH triggered
         abilities on the Python side.
      4. Confirm ``docs/POOL_PARITY.md``'s
         BLOCKED-genuinely_missing list contains Pain for All.

    Closure indicator: ``Effect::PainForAllETBEffect`` +
    ``Effect::PainForAllDamageEchoEffect`` (or the more general
    ``EnchantedDealsDamageThenPropagate`` shape) land in
    ``rust/src/cards.rs``, with parse arms + resolve arms in
    ``state_ops_resolve.rs`` + bridge arms in ``cross_engine.py`` +
    the Aura ``attached_to`` end-to-end substrate (per cards.rs:1240
    deferred note).  Pin renames to ``..._FIXED_parity`` asserting
    the variants + parse arms + resolve arms are present.

    EoE card scale: 1 directly (Pain for All; 4367 17lands decks).
    Closing the Aura ``attached_to`` substrate this card needs ALSO
    unblocks Meltstrider's Resolve + Tractor Beam (3 cards total in
    the Aura-attachment cluster on docs/RESIDUE_CARD_PLANS.md:107-110).
    """
    # 1. Python's bespoke classes exist with the expected interfaces.
    from mtg_bot.effects.bespoke import (
        PainForAllETBEffect,
        PainForAllDamageEchoEffect,
    )
    from mtg_bot.effects.base import Effect as _EffectBase

    assert issubclass(PainForAllETBEffect, _EffectBase), (
        "PainForAllETBEffect should be an Effect subclass "
        "(effects/bespoke.py:352-432).  If this fails, the bespoke "
        "class was restructured -- update this pin."
    )
    assert issubclass(PainForAllDamageEchoEffect, _EffectBase), (
        "PainForAllDamageEchoEffect should be an Effect subclass "
        "(effects/bespoke.py:433-467).  If this fails, the bespoke "
        "class was restructured -- update this pin."
    )

    etb_inst = PainForAllETBEffect()
    echo_inst = PainForAllDamageEchoEffect()
    assert hasattr(etb_inst, "resolve"), (
        "PainForAllETBEffect should have a 'resolve' method."
    )
    assert hasattr(echo_inst, "resolve"), (
        "PainForAllDamageEchoEffect should have a 'resolve' method."
    )

    # 2. Rust crate: NO reference to PainForAll / pain_for_all /
    #    EnchantedDealsDamageThenPropagate in cards.rs or
    #    state_ops_resolve.rs.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_cards_path = repo_root / "rust" / "src" / "cards.rs"
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"

    assert rust_cards_path.exists(), (
        f"Rust source file should exist at {rust_cards_path!r}."
    )
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}."
    )

    cards_src = rust_cards_path.read_text(encoding="utf-8")
    resolve_src_rs = rust_resolve_path.read_text(encoding="utf-8")

    forbidden_substrings = [
        "PainForAll",
        "pain_for_all",
        "PainForAllETBEffect",
        "PainForAllDamageEchoEffect",
        "EnchantedDealsDamageThenPropagate",
        "enchanted_deals_damage_then_propagate",
    ]
    for needle in forbidden_substrings:
        assert needle not in cards_src, (
            f"Pin sentinel: rust/src/cards.rs should NOT yet contain "
            f"{needle!r} (no Pain for All Effect variant exists).  "
            "If this assertion fails, the closure may have landed -- "
            "audit the Rust enum + parse arm + resolve arm and flip "
            "this pin to _FIXED_parity."
        )
        assert needle not in resolve_src_rs, (
            f"Pin sentinel: rust/src/state_ops_resolve.rs should NOT "
            f"yet contain {needle!r} (no Pain for All resolve arm "
            "exists)."
        )

    # 3. Pain for All is loadable + carries both triggered abilities.
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    src = get_active_source()
    pr = src.get_printings().get("Pain for All")
    assert pr is not None, (
        "Pin invariant: 'Pain for All' should be present in the active "
        "CardSource (per docs/POOL_PARITY.md BLOCKED-genuinely_missing "
        "list).  If missing, the EoE data file was regenerated -- "
        "update this pin."
    )
    assert "Enchantment" in pr.card_types, (
        f"Pin invariant: Pain for All should be an Enchantment "
        f"(Aura).  Got: {pr.card_types}."
    )
    enters_ta = next(
        (ta for ta in pr.triggered_abilities if ta.event == Event.ENTERS),
        None,
    )
    assert enters_ta is not None, (
        "Pin invariant: Pain for All should carry an ENTERS triggered "
        "ability (the ETB damage rider).  If absent, the parser "
        "convention changed -- update this pin."
    )
    assert isinstance(enters_ta.effect, PainForAllETBEffect), (
        f"Pin invariant: Pain for All's ENTERS effect should be "
        f"PainForAllETBEffect.  Got: "
        f"{type(enters_ta.effect).__name__}."
    )

    dealt_damage_ta = next(
        (
            ta for ta in pr.triggered_abilities
            if ta.event == Event.DEALT_DAMAGE
        ),
        None,
    )
    assert dealt_damage_ta is not None, (
        "Pin invariant: Pain for All should carry a DEALT_DAMAGE "
        "triggered ability (the damage-echo propagation rider).  If "
        "absent, the parser convention changed -- update this pin."
    )
    assert isinstance(
        dealt_damage_ta.effect, PainForAllDamageEchoEffect
    ), (
        f"Pin invariant: Pain for All's DEALT_DAMAGE effect should be "
        f"PainForAllDamageEchoEffect.  Got: "
        f"{type(dealt_damage_ta.effect).__name__}."
    )

    # 4. POOL_PARITY's BLOCKED-genuinely_missing list contains Pain
    #    for All (the documented worklist entry for this gap).
    pool_parity_path = repo_root / "docs" / "POOL_PARITY.md"
    assert pool_parity_path.exists(), (
        f"docs/POOL_PARITY.md should exist at {pool_parity_path!r}.  "
        "If the doc moved, update this pin's reference."
    )
    pool_parity_src = pool_parity_path.read_text(encoding="utf-8")
    assert "Pain for All" in pool_parity_src, (
        "Pin invariant: docs/POOL_PARITY.md should list 'Pain for All' "
        "(the BLOCKED-genuinely_missing entry).  If absent, the "
        "worklist was updated -- audit this pin's BLOCKED status."
    )

    # 5. EoE cards affected.
    affected_eoe_cards = [
        "Pain for All",
        # Aura with ETB damage + damage-echo propagation.  4367
        # 17lands decks per docs/RESIDUE_CARD_PLANS.md:95.  Sibling
        # cards in the Aura-attachment cluster (also genuinely_missing
        # but with distinct Effect classes): Meltstrider's Resolve
        # (EnchantedCreatureFightsTargetEffect) + Tractor Beam
        # (TractorBeamETBEffect).
    ]
    assert len(affected_eoe_cards) == 1, (
        "The Pain for All Aura-damage-echo gap affects 1 EoE card "
        f"directly.  Enumerated list has {len(affected_eoe_cards)} "
        "entries."
    )


# ---------------------------------------------------------------------------
# Pytest visibility check: ensure the three pin tests are collected.
# ---------------------------------------------------------------------------


def test_vvv_pin_inventory_complete():
    """Sanity check: the VVV batch declares exactly 3 pin tests (one of
    which has since flipped to ``_FIXED_parity`` per the closure cadence).

    Pin batch VVV (round 24 pin-side) originally targeted 3 divergence
    pins.  Pin 1 (Survivor family SourceIsSelf player-subject tautology)
    closed in the 15th Rust slice (2026-05-20) — flipped to
    ``_FIXED_parity`` with assertions inverted per the PPP / MMM / TTT
    closure-cadence precedent.  This sanity check guards against
    accidental deletion or rename of any pin / FIXED-parity function in
    the batch.
    """
    import tests.test_divergence_pins_vvv as _self_mod
    pin_fns = [
        name for name in dir(_self_mod)
        if name.startswith("test_") and name.endswith("_divergence_pin")
    ]
    fixed_fns = [
        name for name in dir(_self_mod)
        if name.startswith("test_") and name.endswith("_FIXED_parity")
    ]
    expected_remaining_pins = {
        "test_cross_engine_real_eoe_command_bridge_sacrifice_unless_tap_no_rust_variant_divergence_pin",
        "test_cross_engine_real_eoe_pain_for_all_aura_damage_echo_no_rust_variant_divergence_pin",
    }
    expected_fixed = {
        "test_cross_engine_real_eoe_survivor_family_source_is_self_player_subject_FIXED_parity",
    }
    assert set(pin_fns) == expected_remaining_pins, (
        "VVV remaining-pin inventory mismatch.  Expected exactly 2 "
        "open-divergence pins (Pin 1 closed in 15th Rust slice):\n"
        f"  {sorted(expected_remaining_pins)}\n"
        f"Got:\n  {sorted(pin_fns)}"
    )
    assert set(fixed_fns) == expected_fixed, (
        "VVV FIXED-parity inventory mismatch.  Expected exactly 1 "
        "closed pin (Pin 1 -- Survivor SourceIsSelf tautology):\n"
        f"  {sorted(expected_fixed)}\n"
        f"Got:\n  {sorted(fixed_fns)}"
    )
