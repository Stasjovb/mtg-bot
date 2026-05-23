"""Divergence-pin tests: batch GG (rounds 1-8 surfaced bugs, test-surface growth round 2).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity. The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 — ``CounterTargetSpell`` bridge drops ``filter_types`` parameter
(``parity/cross_engine.py``).
**CLOSED by ``feature/warping-wail-substrate-cycle-2`` (2026-05-22):**
the Rust ``Effect::CounterTargetSpell`` variant widened from a unit
variant to ``{ filter_types: Vec<String> }`` (mirroring Python's
``frozenset[str]``); ``parse_effect`` / ``to_pydict`` / the resolve
arm thread the field through; ``cross_engine.py``'s bridge arm
propagates the dict-side list-of-strings into Python's
``CounterTargetSpell(filter_types=frozenset(...))``; and
``trajectory.py::_python_spell_effect_to_dict`` gains a matching
reverse-serializer leaf (which was MISSING entirely pre-cycle — a
separate prior gap surfaced by this same closure).  This Pin's test
is renamed ``..._CLOSED_parity`` with the assertion inverted (both
paths now produce the SAME filter_types value).

    Prior bug (now FIXED):
    The cross-engine bridge arm for the Rust dict kind
    ``counter_target_spell`` always constructed Python's
    ``CounterTargetSpell()`` with its default ``filter_types=frozenset()``
    (meaning "counter any spell"), regardless of any ``filter_types`` or
    equivalent restriction present in the source effect dict.  The bridge
    arm was documented to silently drop extra dict keys such as
    ``filter_types``, so a dict
    ``{"kind": "counter_target_spell", "filter_types": ["Creature"]}``
    was translated to an UNFILTERED ``CounterTargetSpell()`` rather than
    ``CounterTargetSpell(filter_types=frozenset({"Creature"}))``.

    CR reference: CR 115.1a (legal targets are determined at cast time;
    if a spell has a type restriction on its target, the restriction
    applies to legal target selection).

Pin 2 — ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
Rust resolve arm reset ``summoning_sick = True`` on library bounce
(``rust/src/state_ops_resolve.rs:10158``).
**CLOSED by 13th Rust slice** (``feature/rust-slice-13-rrr-pins-2-3``):
the explicit ``obj.summoning_sick = true`` stamp has been dropped;
both engines now preserve the pre-bounce value.  This Pin's test is
renamed ``..._FIXED_parity`` with the assertion inverted (both
engines report ``summoning_sick=False``).

    Rust's resolve arm for
    ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
    (the Vanish from Sight / Lost in Space "owner puts it on top or
    bottom of their library" shape) resets ``obj.summoning_sick = true``
    at state_ops_resolve.rs:10158 when moving the object to the library.
    The comment reads "r28 CE1 universal-true default", citing the
    universal-summoning-sickness convention applied to objects entering the
    battlefield.

    This reset is INCORRECT for a library-bounce: CR 400.7 specifies that
    an object that changes zones is treated as a NEW object ONLY when it
    re-enters a zone it can be put on the battlefield from (i.e., only
    when it enters the battlefield again, not when it enters the library).
    A creature bounced to the library carries its current summoning_sick
    state into the library and would re-enter the battlefield fresh
    (gaining summoning sickness then per CR 302.6).  Stamping
    summoning_sick=True on a library card is meaningless / misleading and
    diverges from Python's behavior.

    Python's ``zone_moves.OwnerPutsTargetArtifactOrCreatureOnTopOrBottom
    OfLibrary.resolve`` (``effects/generic/zone_moves.py:98-124``) does
    NOT touch ``obj.summoning_sick`` during the bounce — the field retains
    its pre-bounce value.

    CR reference: CR 400.7 (objects that change zones are treated as new
    objects, but only upon entering the battlefield; a library card is not
    on the battlefield so the new-object rule doesn't apply until it would
    re-enter the battlefield).

    Verified observable divergence (creature with summoning_sick=False
    bounced to library via the resolve arm):
      * Python: ``library[0].summoning_sick`` → False (preserved).
      * Rust:   ``library_snapshot(1)[1]["summoning_sick"]`` → True
                (incorrectly stamped True at state_ops_resolve.rs:10158).

Pin 3 — ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
Rust resolve arm always placed the card at BOTTOM of library
(``push()``) while Python defaults to TOP (``insert(0, obj)``)
(``rust/src/state_ops_resolve.rs:10166``).
**CLOSED by 13th Rust slice** (``feature/rust-slice-13-rrr-pins-2-3``):
Rust converged on Python — ``lib_mut.push(obj)`` was changed to
``lib_mut.insert(0, obj)``.  Both engines' no-agent default now
places the bounced card at the TOP of the library.  This Pin's test
is renamed ``..._FIXED_parity`` with the assertion inverted (both
engines report index 0).

    The same Rust resolve arm at state_ops_resolve.rs:10166 calls
    ``lib_mut.push(obj)``.  In the Rust library representation, the Vec's
    tail (index ``len-1``) corresponds to the BOTTOM of the library (cards
    are drawn from index 0 = top).  Therefore ``push()`` always places the
    bounced card at the BOTTOM of the library.

    Python's ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary.
    resolve`` at zone_moves.py:119-123 defaults to ``choice = 0`` (no
    agent) which selects ``owner.library.insert(0, obj)`` — the TOP of the
    library.  The owner's agent can choose bottom (choice=1); without an
    agent the default is top.

    The oracle text of Lost in Space / Vanish from Sight reads "owner puts
    it on TOP OR BOTTOM of their library" — the owner (not the spell's
    controller) makes the choice.  CR 401.1 / CR 115.9a: the owner chooses
    at resolution.  Defaulting to bottom without offering the owner the
    choice (Rust) diverges from both Python and the correct CR behavior.

    CR reference: CR 401.1 (library ordering is determined by the owner;
    "top" = card drawn next), CR 115.9a (if there's a choice with no
    instruction, the player making the choice decides).

    Verified observable divergence (creature bounced to a library with an
    existing card; no agent on either side):
      * Python: creature lands at library index 0 (TOP).
      * Rust:   creature lands at library index len-1 (BOTTOM) — appended
                via ``push()`` to the tail of the Vec.

Dropped pins
------------

  * High Market / ``sacrifice_another_creature_or_artifact`` crash
    (surfaced batch W): the crash occurs in Python's
    ``_activate_ability`` at the bare ``options[0]`` index when called
    WITHOUT a legal sacrifice target (bypassing the ``legal_actions``
    gate).  The ``legal_actions`` check correctly prevents the activation
    from being surfaced, making the crash reachable only by direct
    low-level API call — not through normal game flow.  Rust's
    ``apply_action`` with no sacrifice victim raises ``ValueError`` (also
    correct refusal) but via a different exception type.  The pin would
    document a Python internal-API crash at the wrong abstraction level,
    not a cross-engine game-simulation divergence.  Dropped; the gate
    behavior (both engines refuse the activation) is consistent.

  * Ragost / ``sacrifice_food=True`` crash (surfaced batch Y): same shape
    as High Market drop above — Python's ``_activate_ability`` crashes at
    ``options[0]`` when called without a Food permanent; Rust raises
    ``ValueError``.  The ``legal_actions`` gate correctly prevents it in
    normal flow.  Dropped for the same reason.

  * ``grant_keyword_to_target_creature_until_eot`` for keyword="trample"
    or "haste" (surfaced as potential Pin 5): the DD Pin 2 already covers
    the bridge arm's class-mismatch for ALL keyword values (it constructs
    ``PumpTargetCreatureUntilEOT`` regardless of keyword).  A separate pin
    for trample/haste would document the same arm defect.  Dropped as
    redundant with DD Pin 2.

  * ``IS_CAST`` predicate-bridge ``subject_is_artifact`` returning
    Subject(slot=None) → predicate-false (surfaced batch AA): the
    IS_CAST trigger + subject_is_artifact predicate evaluation path
    requires a real game trajectory (card cast, trigger fires, predicate
    evaluated) to be reproducible.  The predicate evaluation depends on
    the bridge's Subject slot-resolution logic which has no stable
    single-observable; the setup is too fragile for a stable pin without
    further isolation work.  Dropped.
"""

from __future__ import annotations

import importlib.util

import pytest

# ---------------------------------------------------------------------------
# Rust-engine guard (required for Pins 2 and 3).
# ---------------------------------------------------------------------------

_RUST_ENGINE_AVAILABLE = importlib.util.find_spec("mtg_bot_engine") is not None

pytestmark_rust = pytest.mark.skipif(
    not _RUST_ENGINE_AVAILABLE,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_base_state():
    """Minimal two-player GameState for Python-only pins."""
    from mtg_bot.game import GameState, Player
    from mtg_bot.turn import Step

    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _make_creature_printing(name="Test Creature", power=2, toughness=2):
    """Return a minimal Creature CardPrinting."""
    from mtg_bot.cards.base import CardPrinting, ManaCost

    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=power,
        toughness=toughness,
        produces=frozenset(),
    )


def _make_sorcery_printing(name="Test Sorcery"):
    """Return a minimal Sorcery CardPrinting."""
    from mtg_bot.cards.base import CardPrinting, ManaCost

    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Sorcery",
        supertypes=(),
        card_types=("Sorcery",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )


def _put_on_bf(state, printing, owner_id):
    """Place a new GameObject on the battlefield (no ETB triggers)."""
    from mtg_bot.game import Zone

    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = False
    obj.damage = 0
    obj.etb_timestamp = state.next_timestamp
    state.next_timestamp += 1
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Pin 1 — CounterTargetSpell bridge drops filter_types
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_counterspell_bridge_propagates_filter_types_CLOSED_parity():
    """**Warping Wail Cycle 2 substrate closure (2026-05-22).** The
    bridge mistranslation pinned here is now CLOSED — Pin 1 flips from
    divergence-pin to parity-pin (mirrors the established pattern for
    other former-divergence pins in this file, e.g. Vanish from Sight
    summoning_sick reset).

    Prior bug (now FIXED):
      ``src/mtg_bot/parity/cross_engine.py`` — the bridge arm for Rust
      dict kind ``counter_target_spell`` constructed Python's
      ``CounterTargetSpell()`` with its default ``filter_types=
      frozenset()`` regardless of any ``filter_types`` value on the
      dict.  A hypothetical dict with ``filter_types`` present would
      have been silently dropped, resulting in an UNFILTERED
      counterspell instead of a type-restricted one.

    Fix (this slice, ``feature/warping-wail-substrate-cycle-2``):
      * Rust ``Effect::CounterTargetSpell`` widened from unit variant
        to ``{ filter_types: Vec<String> }`` (mirroring Python's
        ``frozenset[str]``).
      * Rust ``parse_effect`` accepts optional ``filter_types`` list-
        of-strings; missing / null / empty → empty-Vec back-compat.
      * Rust ``to_pydict`` emits the field only when non-empty (byte-
        identical to pre-Cycle-2 round-trip for the empty case).
      * Rust resolve arm intersects the stack item's
        ``card_types`` with ``filter_types`` (when non-empty) on top
        of the Phase-2 uncounterability gates.
      * ``cross_engine.py`` bridge arm threads ``filter_types`` from
        dict → ``frozenset[str]`` on the Python class.
      * ``trajectory.py::_python_spell_effect_to_dict`` adds the
        ``CounterTargetSpell`` leaf (was MISSING entirely pre-cycle —
        a separate prior gap surfaced by this same closure).

    What's right (CR 115.1a): if a spell has a type restriction on
    its target ("counter target Creature spell"), only legal targets
    matching that type restriction may be chosen.  The bridge now
    propagates ``filter_types`` so the type restriction round-trips
    Rust → Python without loss.

    Probe shape (CLOSED parity — both paths agree):
      1. Build a minimal Python state.
      2. Place a Sorcery object on the stack.
      3. Path A: instantiate
         ``CounterTargetSpell(filter_types=frozenset({"Creature"}))``
         directly; call legal_targets; assert the Sorcery is NOT
         included.
      4. Path B: call ``_ta_dict_to_python_effect`` with
         ``{"kind": "counter_target_spell", "filter_types":
         ["Creature"]}``; assert the returned class carries the
         propagated ``filter_types=frozenset({"Creature"})``; call
         legal_targets; assert the Sorcery is NOT included
         (CLOSED — matches Path A).
      5. Assert Path A and Path B AGREE — the divergence is closed.

    This pin does not require the Rust PyO3 extension.
    """
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    state = _new_base_state()

    sorcery_printing = _make_sorcery_printing("Test Sorcery")
    sorcery_obj = state.new_object(sorcery_printing, owner_id=1, zone=Zone.HAND)

    class _FakeStackItem:
        """Minimal StackItem shim sufficient for legal_targets inspection."""
        def __init__(self, source):
            self.source = source
            self.ability = None     # marks as a spell, not triggered ability
            self.countered = False
            self.controller_id = 1

    fake_stack_item = _FakeStackItem(sorcery_obj)
    state.stack.append(fake_stack_item)

    assert len(state.stack) == 1, (
        f"Expected exactly one item on the stack; got {len(state.stack)}"
    )

    # ------------------------------------------------------------------
    # Path A: CounterTargetSpell with filter_types={"Creature"} directly.
    # A Sorcery is NOT a Creature spell → legal_targets should be empty.
    # ------------------------------------------------------------------
    cs_creature = CounterTargetSpell(filter_types=frozenset({"Creature"}))
    legal_a = cs_creature.legal_targets(state, controller_id=0)

    assert legal_a == [], (
        "Path A (filter_types={'Creature'}): a Sorcery is not a Creature "
        "spell; it should NOT appear in legal_targets. "
        f"Got: {legal_a}"
    )

    # ------------------------------------------------------------------
    # Path B: bridge translation of a type-restricted counter dict.
    # **POST-CYCLE-2 (CLOSED):** the bridge propagates filter_types →
    # returns CounterTargetSpell(filter_types=frozenset({"Creature"}))
    # → the Sorcery is NOT included (matches Path A).
    # ------------------------------------------------------------------
    effect_dict = {
        "kind": "counter_target_spell",
        "filter_types": ["Creature"],
    }
    bridge_effect = _ta_dict_to_python_effect(effect_dict)

    assert isinstance(bridge_effect, CounterTargetSpell), (
        "Bridge: _ta_dict_to_python_effect for counter_target_spell "
        f"should return CounterTargetSpell; got {type(bridge_effect).__name__}"
    )
    # **CLOSED — Cycle 2 substrate landed:** the bridge now
    # propagates filter_types.
    assert bridge_effect.filter_types == frozenset({"Creature"}), (
        "Bridge class pin (CLOSED): post-Cycle-2 the bridge propagates "
        "filter_types; returned instance should have "
        "filter_types=frozenset({'Creature'}). "
        f"Got: {bridge_effect.filter_types}. "
        "If this assertion fails, the Cycle-2 substrate landing has "
        "regressed; do NOT 'fix' the test — fix the regression."
    )

    legal_b = bridge_effect.legal_targets(state, controller_id=0)

    assert legal_b == [], (
        "Path B (bridge, CLOSED): the Sorcery is NOT a legal target — "
        "filter_types={'Creature'} now propagates through the bridge "
        "(Cycle-2 substrate landing). "
        f"Got: {legal_b}"
    )

    # ------------------------------------------------------------------
    # Cross-path parity: the two paths now AGREE on legality.
    # ------------------------------------------------------------------
    assert legal_a == legal_b, (
        "Cross-path parity (CLOSED): CounterTargetSpell with "
        "filter_types={'Creature'} directly ([] targets) and the "
        "bridge output (also [] targets) must agree now that the "
        "bridge propagates filter_types. "
        f"legal_a={legal_a}, legal_b={legal_b}"
    )


# ---------------------------------------------------------------------------
# Pin 2 — Vanish from Sight: Rust resets summoning_sick=True on library bounce
# ---------------------------------------------------------------------------

@pytestmark_rust
def test_cross_engine_real_eoe_vanish_from_sight_summoning_sick_reset_on_library_bounce_FIXED_parity():
    """Assert the Rust-vs-Python parity for
    ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
    preserving ``summoning_sick`` on library bounce (RRR Pin 2 closure,
    13th Rust slice).

    Bug location:
      Rust: ``rust/src/state_ops_resolve.rs:10158`` —
        ``obj.summoning_sick = true; // r28 CE1 universal-true default``
        This line appears inside the resolve arm for
        ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
        (Vanish from Sight / Lost in Space shape) immediately after the
        object is removed from the battlefield and before it is inserted
        into the library.

      Python: ``src/mtg_bot/effects/generic/zone_moves.py:98-124`` —
        ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary.resolve``
        does NOT touch ``obj.summoning_sick`` during the library bounce.
        The field retains its pre-bounce value.

    What's right: Python (CR 400.7).
      A creature bounced to the library does not enter the battlefield;
      CR 302.6 (summoning sickness applies "when a creature enters the
      battlefield") does not fire.  The library card's ``summoning_sick``
      field is irrelevant while in the library, so stamping it True there
      is wrong/misleading.  When the card later enters the battlefield
      (e.g. cast again), the ETB path will correctly stamp summoning_sick
      per CR 302.6.  Stamping True at library-bounce time is a spurious
      reset that would cause a discrepancy between snapshot reads and any
      state that is cloned then re-entered.

    CR reference: CR 400.7 (zone-change new-object convention), CR 302.6
    (summoning sickness triggers on entering the battlefield, not on
    entering the library).

    Verified observable divergence (creature with summoning_sick=False,
    p1 owns and controls it, no agent on either side):
      * Python: ``victim.summoning_sick`` in library → False (preserved).
      * Rust:   ``library_snapshot(1)[idx]["summoning_sick"]`` → True
                (incorrectly stamped True at state_ops_resolve.rs:10158).

    Probe shape:
      1. Build Rust and Python states.
      2. Register/inject a 2/2 Creature on p1's battlefield on both sides.
      3. Force ``summoning_sick = False`` on both sides (simulate a creature
         that has been on the battlefield for a full turn).
      4. Register/inject a Vanish-from-Sight-shaped Instant on both sides.
      5. Python side: resolve
         ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
         directly targeting the victim (no agent → top placement by default).
         Rust side: push the spell to the stack targeting the victim, then
         ``resolve_top_of_stack()``.
      6. Assert Python victim's ``summoning_sick`` in library == False.
         Assert Rust victim's ``summoning_sick`` in library snapshot == True.
      7. Assert the two engines disagree.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.zone_moves import (
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state, build_rust_state

    # --- Python setup ---
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    creature_printing = _make_creature_printing("Victim Creature", power=2, toughness=2)

    py_victim = py_state.new_object(creature_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    py_victim.summoning_sick = False
    py_victim.tapped = False
    py_victim.damage = 0
    py_victim.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_victim)

    assert py_victim.summoning_sick is False, (
        "Python: victim summoning_sick should be False before bounce"
    )

    # --- Rust setup ---
    rust_state = build_rust_state(spec)

    ZONE_BATTLEFIELD = 2
    rust_victim_id = rust_state.register_and_inject_object(
        {
            "name": "Victim Creature",
            "card_types": ["Creature"],
            "mana_cost": {},
            "effects": [],
            "power": 2,
            "toughness": 2,
        },
        1,               # controller = p1
        ZONE_BATTLEFIELD,
    )
    rust_state.force_set_summoning_sick(rust_victim_id, False)
    assert rust_state.is_summoning_sick(rust_victim_id) is False, (
        "Rust: victim summoning_sick should be False before bounce"
    )

    rust_vanish_id = rust_state.register_and_inject_object(
        {
            "name": "Vanish from Sight",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [
                {
                    "kind": (
                        "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library"
                    ),
                }
            ],
        },
        0,               # controller = p0 (caster)
        ZONE_BATTLEFIELD,
    )

    # --- Python: resolve the bounce effect directly ---
    effect = OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary()
    effect.resolve(
        py_state,
        controller_id=0,
        targets=(("permanent", py_victim.id),),
    )

    py_lib1 = py_state.players[1].library
    assert len(py_lib1) >= 1, (
        "Python: p1's library should contain the bounced creature"
    )
    # Default (no agent) places the creature at index 0 (TOP of library).
    py_victim_in_lib = next(
        (o for o in py_lib1 if o.id == py_victim.id), None
    )
    assert py_victim_in_lib is not None, (
        "Python: bounced victim should be in p1's library"
    )
    py_ss_in_lib = py_victim_in_lib.summoning_sick

    # --- Rust: push to stack with target, then resolve ---
    # push_to_stack_with_target(spell_id, controller_player_id, target_obj_id)
    rust_state.push_to_stack_with_target(rust_vanish_id, 0, rust_victim_id)
    assert rust_state.stack_size() == 1, (
        f"Rust: stack should have the Vanish spell; size={rust_state.stack_size()}"
    )
    rust_state.resolve_top_of_stack()
    assert rust_state.stack_size() == 0, (
        f"Rust: stack should be empty after resolve; size={rust_state.stack_size()}"
    )

    rust_lib1 = rust_state.library_snapshot(1)
    assert len(rust_lib1) >= 1, (
        "Rust: p1's library should contain the bounced creature"
    )
    rust_victim_entry = next(
        (e for e in rust_lib1 if e.get("id") == rust_victim_id), None
    )
    assert rust_victim_entry is not None, (
        "Rust: bounced victim should appear in p1's library snapshot"
    )
    rust_ss_in_lib = rust_victim_entry["summoning_sick"]

    # --- Per-engine divergence assertions ---
    # Python: summoning_sick preserved from pre-bounce value (False).
    assert py_ss_in_lib is False, (
        "Python: OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary.resolve "
        "does NOT touch summoning_sick — the pre-bounce value (False) should be "
        "preserved in the library. Bug-fix for Rust should make both engines "
        "agree on False (or at least agree that it's not forcibly True). "
        f"Got: {py_ss_in_lib}"
    )

    # Rust (post-RRR-Pin-2 closure, 13th Rust slice): summoning_sick
    # preserved on library bounce — the explicit
    # ``obj.summoning_sick = true`` stamp has been dropped from
    # ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``.
    assert rust_ss_in_lib is False, (
        "Rust (post-13th-slice): OwnerPutsTargetArtifactOrCreatureOnTop"
        "OrBottomOfLibrary resolve arm should preserve the pre-bounce "
        "summoning_sick value (False) — the explicit "
        "'obj.summoning_sick = true' stamp was dropped (RRR Pin 2 "
        "closure). "
        f"Got: {rust_ss_in_lib}"
    )

    # Cross-engine parity: both engines preserve the pre-bounce value.
    assert py_ss_in_lib == rust_ss_in_lib == False, (
        "Cross-engine parity: Python (False) and Rust (False) both "
        "preserve summoning_sick on library bounce post-RRR-Pin-2 "
        "closure. "
        f"Python={py_ss_in_lib}, Rust={rust_ss_in_lib}"
    )


# ---------------------------------------------------------------------------
# Pin 3 — Vanish from Sight: Rust places card at BOTTOM of library (push())
#          while Python defaults to TOP (insert(0, obj))
# ---------------------------------------------------------------------------

@pytestmark_rust
def test_cross_engine_real_eoe_vanish_from_sight_library_position_top_default_FIXED_parity():
    """Assert the Rust-vs-Python parity for
    ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
    placing the bounced card at the TOP of the library via
    ``insert(0, obj)`` (head of Vec) on the no-agent default path —
    matching Python's ``library.insert(0, obj)`` (RRR Pin 3 closure,
    13th Rust slice; Option A "Rust converges on Python").

    Bug location:
      Rust: ``rust/src/state_ops_resolve.rs:10166`` —
        ``lib_mut.push(obj); // post-CE3: bottom = tail of Vec``
        The CE3 convention is that Vec index 0 = top of library (the card
        drawn first), and Vec tail (index len-1) = bottom.  ``push()``
        unconditionally appends to the tail, meaning ALL bounces go to the
        BOTTOM with no owner choice offered.

      Python: ``src/mtg_bot/effects/generic/zone_moves.py:87-123`` —
        The owner picks top vs. bottom via ``agent.choose_mode``; without
        an agent the default is ``choice = 0`` → ``owner.library.insert(0,
        obj)`` → TOP of library.

    What's right: Python (with owner choice per CR 401.1 / CR 115.9a).
      The oracle text of Lost in Space / Vanish from Sight explicitly says
      "owner puts it on TOP OR BOTTOM of their library."  CR 401.1 defines
      the top of a library as the first card that would be drawn.  CR 115.9a
      says if a player has a choice with no further instruction, the player
      makes the choice at resolution time.  Rust's hard-coded bottom
      placement skips the owner's choice entirely.

    CR reference: CR 401.1 (library top = first drawn), CR 115.9a (owner
    chooses at resolution), CR 608.2c (for effects that say "choose", the
    player making the choice does so at resolution).

    Verified observable divergence (no agent on either side; library has a
    sentinel card before the bounce so position is unambiguous):
      * Python: bounced creature lands at library index 0 (TOP).
      * Rust:   bounced creature lands at library index 1 (BOTTOM, after
                the sentinel at index 0) — appended via ``push()``.

    Probe shape:
      1. Build Rust and Python states with a sentinel Sorcery in p1's
         library (so we can distinguish top vs. bottom unambiguously).
      2. Register/inject a 2/2 Creature on p1's battlefield.
      3. Python: resolve the bounce effect targeting the creature.
         Rust: push the Vanish spell to the stack targeting the creature
         and resolve_top_of_stack().
      4. Assert Python victim is at library index 0 (TOP).
         Assert Rust victim is at library index > 0 (appended at BOTTOM).
      5. Assert the two engines disagree on position.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.zone_moves import (
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state, build_rust_state

    # --- Python setup ---
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    sentinel_printing = _make_sorcery_printing("Sentinel Card")
    creature_printing = _make_creature_printing("Victim Creature", power=2, toughness=2)

    # Place sentinel in p1's library (index 0 = top initially).
    py_sentinel = py_state.new_object(sentinel_printing, owner_id=1, zone=Zone.LIBRARY)
    py_state.players[1].library.append(py_sentinel)

    py_lib_before = [o.printing.name for o in py_state.players[1].library]
    assert py_lib_before == ["Sentinel Card"], (
        f"Python: library before bounce should be [Sentinel Card]; got {py_lib_before}"
    )

    # Place creature on p1's battlefield.
    py_victim = py_state.new_object(creature_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    py_victim.summoning_sick = False
    py_victim.tapped = False
    py_victim.damage = 0
    py_victim.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_victim)

    # --- Rust setup ---
    rust_state = build_rust_state(spec)

    ZONE_LIBRARY = 1
    ZONE_BATTLEFIELD = 2

    rust_sentinel_id = rust_state.register_and_inject_object(
        {
            "name": "Sentinel Card",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        1,            # owner = p1
        ZONE_LIBRARY,
    )
    rust_lib_before = rust_state.library_snapshot(1)
    assert len(rust_lib_before) == 1, (
        f"Rust: library before bounce should have 1 sentinel; got {rust_lib_before}"
    )

    rust_victim_id = rust_state.register_and_inject_object(
        {
            "name": "Victim Creature",
            "card_types": ["Creature"],
            "mana_cost": {},
            "effects": [],
            "power": 2,
            "toughness": 2,
        },
        1,               # controller = p1
        ZONE_BATTLEFIELD,
    )
    rust_state.force_set_summoning_sick(rust_victim_id, False)

    rust_vanish_id = rust_state.register_and_inject_object(
        {
            "name": "Vanish from Sight",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [
                {
                    "kind": (
                        "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library"
                    ),
                }
            ],
        },
        0,               # controller = p0 (caster)
        ZONE_BATTLEFIELD,
    )

    # --- Python: resolve the bounce (no agent → top placement) ---
    effect = OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary()
    effect.resolve(
        py_state,
        controller_id=0,
        targets=(("permanent", py_victim.id),),
    )

    py_lib_after = [o.printing.name for o in py_state.players[1].library]
    assert len(py_lib_after) == 2, (
        f"Python: library should have 2 cards after bounce; got {py_lib_after}"
    )
    py_victim_index = py_lib_after.index("Victim Creature")

    # --- Rust: push to stack targeting victim, then resolve ---
    # push_to_stack_with_target(spell_id, controller_player_id, target_obj_id)
    rust_state.push_to_stack_with_target(rust_vanish_id, 0, rust_victim_id)
    assert rust_state.stack_size() == 1, (
        f"Rust: stack should have the Vanish spell; size={rust_state.stack_size()}"
    )
    rust_state.resolve_top_of_stack()
    assert rust_state.stack_size() == 0, (
        f"Rust: stack should be empty after resolve; size={rust_state.stack_size()}"
    )

    rust_lib_after = rust_state.library_snapshot(1)
    assert len(rust_lib_after) == 2, (
        f"Rust: library should have 2 cards after bounce; got {rust_lib_after}"
    )
    rust_lib_names = [e["printing_name"] for e in rust_lib_after]
    rust_victim_index = rust_lib_names.index("Victim Creature")

    # --- Per-engine position assertions ---
    # Python: no-agent default selects choice=0 → insert(0, obj) → TOP.
    assert py_victim_index == 0, (
        "Python: OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary "
        "with no agent defaults to TOP (insert(0, obj) at zone_moves.py:120). "
        "Victim Creature should be at library index 0 (top). "
        f"Got index={py_victim_index}, library={py_lib_after}"
    )

    # Rust (post-RRR-Pin-3 closure, 13th Rust slice): no-agent default
    # is now ``lib_mut.insert(0, obj)`` (TOP = head of Vec), matching
    # Python's ``library.insert(0, obj)``. Victim Creature lands at
    # index 0 above the sentinel.
    assert rust_victim_index == 0, (
        "Rust (post-13th-slice): OwnerPutsTargetArtifactOrCreatureOnTop"
        "OrBottomOfLibrary resolve arm now calls 'lib_mut.insert(0, "
        "obj)' (head of Vec = TOP of library) — RRR Pin 3 closure. "
        "Victim Creature should be at index 0 (above the sentinel). "
        f"Got index={rust_victim_index}, library={rust_lib_names}"
    )

    # Cross-engine parity: Python TOP-default and Rust TOP-default
    # agree.
    assert py_victim_index == rust_victim_index == 0, (
        "Cross-engine parity: Python victim at index 0 (top) must "
        "equal Rust victim at index 0 (top) post-RRR-Pin-3 closure. "
        f"Python index={py_victim_index}, Rust index={rust_victim_index}"
    )
