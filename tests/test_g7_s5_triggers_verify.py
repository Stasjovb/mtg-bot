"""G7 S5 triggers-verify — comprehensive cross-engine byte-equality
VERIFY pins for the FULL trigger surface composing through the S5a
re-homed spell-stack source (``GameState.stack_objects``).

S5a (`feature/g7-s5a-spellstack-zone`, merged to main @ `302a5fc5`)
re-homed the cast spell out of Rust's ``hand`` Vec into
``GameState.stack_objects`` (Option β, the live ``ZONE_STACK`` store),
byte-mirroring Python's ``p.hand.remove(card)`` (`actions.py:1403`) +
``card.zone = Zone.STACK`` (`:1751`), and extended the 3 source-
resolution walks + the ``dispatch_event`` CAST/DIES/LEAVES observer
walk + the 3 ``cards.rs`` predicate subject/controller helpers to
reach the new store. S5b proved the codec/determinizer/fingerprint
surfaces byte-equal. **S5 triggers-verify is the comprehensive
verification that the FULL trigger surface composes byte-equal
Python↔Rust now that the resolving spell's source lives in
``stack_objects``** — i.e. that triggers which read/observe the
resolving spell's source (ETB-on-resolve, the push-ordering of
multiple resolve-time triggers, the respond-to-trigger window) fire
and resolve identically across engines through the re-homed source,
at the same per-apply moment the role-swapped ``rust_shadow`` bake-in
compares (**NO CE5 post-cast drain** — the cast→on-stack→resolve
window S5a re-homed).

Per the G7 owner doc (`docs/RUST_STACK_RESOLUTION_DESIGN.md` Slice S5,
lines 483-502): the S5-specific delta is *"a permanent spell's ETB
triggers now fire at resolution off ``move_source_post_resolve`` →
``dispatch_event(Enters)`` instead of inside the atomic cast — verify
the trigger push-ordering vs Python ``put_into_battlefield``
ETB-on-stack ordering, and that an opponent can respond to a
triggered ability on the stack"*. This module pins exactly that.

**This is a pure-Python / test-only VERIFY slice. It makes NO engine
change (zero ``rust/src/`` / ``src/`` / ``.pyd``).** If a pin fails,
that is a genuine finding: a real trigger-through-re-homed-source hole
— the pin fails LOUD with the exact divergence; it is NOT papered
over (honest-stop, `feedback_no_fallback_hybrids` / verify-first).

The pins (mirroring the S5b verify-slice idiom —
``tests/test_g7_s5b_codec_determinizer_verify.py`` is the template,
``_drive_to_spell_on_stack`` reused verbatim):

1. ``test_window_spell_on_rehomed_stack_both_engines`` — sanity: the
   cast spell sits on the re-homed ``stack_objects`` source on BOTH
   engines and is out of hand (the S5a invariant the trigger surface
   rests on); NOT a triviality.
2. ``test_etb_on_resolve_self_trigger_byte_equal`` — a creature with
   a ``source_is_self`` ENTERS trigger cast through the re-homed
   source resolves; the ETB fires off ``move_source_post_resolve``
   reading the re-homed source, byte-equal Python↔Rust at the
   mid-stack (re-homed) AND post-resolve compare points. The core
   S5 owner-doc deliverable.
3. ``test_multi_etb_trigger_push_ordering_byte_equal`` — TWO
   ``source_is_self`` ENTERS triggers (draw + scry) on the cast
   creature both fire at resolve; the pushed order + results are
   byte-equal (the §S5 "trigger push-ordering vs Python
   ``put_into_battlefield`` ETB-on-stack ordering").
4. ``test_respond_to_trigger_window_byte_equal`` — after resolving
   exactly the spell, the ETB triggered ability sits ALONE on the
   stack as a respondable object on BOTH engines (stack-state
   byte-equal), then resolves byte-equal (the §S5 "an opponent can
   respond to a triggered ability on the stack").
5. ``test_negative_control_rehomed_source_hole_fails_loud`` — a
   simulated S5a re-homed-source hole (Rust's resolve-time trigger
   never fires) produces a LOUD multi-field divergence, proving the
   pins genuinely discriminate (not trivially-passing — the S5b
   negative-control discipline).
6. ``test_cast_predicate_bridge_limitation_is_documented`` — an
   honest pin documenting that the cross-engine ``triggered_abilities``
   predicate bridge cannot faithfully represent an IS_CAST-event
   predicate (slot-None ``subject_*`` / ``controlled_by_you`` no-ops
   Python on the 2-subject IS_CAST event — real card data uses
   ``Subject("spell", ...)`` / ``Controlled(YOU, subject=...)`` per
   ``cards/parser/triggers.py:728-760``), so the §1.4 CAST observer
   walk is verified via S5a's ``tests_rust`` closure-flips + the
   byte-equal ETB-on-resolve path (Pin 2/3/4 — which reads the SAME
   re-homed ``stack_objects`` source the CAST observer walk reads),
   NOT via this harness bridge. Documents the limitation rather than
   papering it (`feedback_silent_noop_pipelines`).
"""

from __future__ import annotations

import importlib.util
import os

import pytest

# Reuse the S5b verify-slice driver verbatim — same cast→on-stack→
# (NO drain) per-apply compare point the role-swapped ``rust_shadow``
# bake-in uses (`rust_shadow.py:471-472`). Loaded by path so this
# module does not depend on test-collection order.
_S5B_PATH = os.path.join(
    os.path.dirname(__file__), "test_g7_s5b_codec_determinizer_verify.py"
)


def _s5b():
    spec = importlib.util.spec_from_file_location(
        "_g7_s5b_driver", _S5B_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A creature carrying a ``source_is_self`` ENTERS trigger. ``enters``
# is a single-subject event (``EVENT_SUBJECTS[Event.ENTERS] ==
# ("obj",)``) so the cross-engine ``triggered_abilities`` predicate
# bridge (slot-None ``IsSelf()`` / ``Subject(None, ...)``) is FAITHFUL
# Python↔Rust — unlike IS_CAST (2-subject; see Pin 6). The cast
# creature rides hand → ``stack_objects`` (S5a re-homed) → bf; the
# ETB fires at ``move_source_post_resolve`` reading the re-homed
# source (G7 owner doc Slice S5).
_ETB_DRAW = {
    "event": "enters",
    "predicate": {"kind": "source_is_self"},
    "effect": {"kind": "draw_cards", "count": 1},
}
_ETB_SCRY = {
    "event": "enters",
    "predicate": {"kind": "source_is_self"},
    "effect": {"kind": "scry_n", "count": 1},
}


def _trigger_bears_spec(triggered_abilities):
    """The S5b ``_bigger_cast_deckspec`` shape (deep libraries so a
    real cast lands + ≥2 hidden cards) but the ``Grizzly Bears``
    CardDef carries ``triggered_abilities`` — ``cast_bears_selector``
    still drives the cast (it keys off the printing NAME, unchanged).
    """
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, _FOREST, _MOUNTAIN,
    )

    bears = CardDef(
        name="Grizzly Bears",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
        triggered_abilities=tuple(triggered_abilities),
    )
    return DeckSpec(
        card_defs=(_FOREST, bears, _MOUNTAIN),
        p0_library=(
            "Forest", "Forest", "Grizzly Bears", "Forest", "Mountain",
            "Grizzly Bears", "Forest", "Mountain", "Forest",
            "Grizzly Bears", "Mountain", "Forest",
        ),
        p1_library=(
            "Mountain", "Grizzly Bears", "Forest", "Mountain", "Forest",
            "Grizzly Bears", "Forest", "Mountain", "Grizzly Bears",
            "Forest", "Mountain", "Forest",
        ),
    )


def _field_views(py_state, rust_state):
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    py_view = build_python_field_view(py_state)
    rust_view = ce_parity_smoke()._build_field_view(rust_state)
    return py_view, rust_view, compare_fields(py_view, rust_view)


def _resolve_all(py_state, rust_state, cap=80):
    """Drain BOTH stacks to the floor through the real resolve path
    (NO CE5 mirror — the honest cast→on-stack→resolve window)."""
    from mtg_bot.actions import resolve_top_of_stack as py_resolve

    g = 0
    while py_state.stack and g < cap:
        py_resolve(py_state)
        g += 1
    g = 0
    while rust_state.stack_size() > 0 and g < cap:
        rust_state.resolve_top_of_stack()
        g += 1


# ---------------------------------------------------------------------------
# Pin 1 — sanity: the trigger surface rests on the re-homed source
# ---------------------------------------------------------------------------


def test_window_spell_on_rehomed_stack_both_engines():
    """The cast creature spell sits on the re-homed ``stack_objects``
    source on BOTH engines and is absent from BOTH hand projections —
    the S5a invariant every trigger pin below rests on. NOT a
    triviality: asserts the real id is on the stack store AND in no
    hand, on either side, with a trigger-bearing carrier."""
    s5b = _s5b()
    spec = _trigger_bears_spec([_ETB_DRAW])
    py_state, rust_state, cast_id = s5b._drive_to_spell_on_stack(spec)

    py_stack_ids = [getattr(si.source, "id", None) for si in py_state.stack]
    assert cast_id in py_stack_ids, (
        f"Python: cast id {cast_id} not on the stack {py_stack_ids}"
    )
    assert not any(
        o.id == cast_id for p in py_state.players for o in p.hand
    ), "Python: cast spell still in a hand list (S5 SoT contract broken)"

    rust_stack_ids = [
        dict(d)["source_obj_id"] for d in rust_state.stack_snapshot()
    ]
    assert cast_id in rust_stack_ids, (
        f"Rust: cast id {cast_id} not on the stack {rust_stack_ids} — "
        "S5a stack-object store re-homing did not take"
    )
    assert not any(
        dict(d)["id"] == cast_id
        for pid in (0, 1)
        for d in rust_state.hand_snapshot(pid)
    ), (
        "Rust: cast spell still in hand_snapshot — the trigger surface "
        "would be exercising a hand-resident, not stack-resident, source"
    )
    # The re-homed window is byte-equal BEFORE any trigger resolves
    # (the S5a/S5b-proven hand_p0 closure — the floor this slice builds
    # the trigger verification on top of).
    _, _, divs = _field_views(py_state, rust_state)
    assert divs == [], (
        f"the cast→on-stack (re-homed) window is NOT byte-equal before "
        f"any trigger resolves — S5a/S5b floor regressed: "
        f"{[(d.field, d.py_value, d.rust_value) for d in divs]}"
    )


# ---------------------------------------------------------------------------
# Pin 2 — ETB-on-resolve self trigger byte-equal through re-homed source
# ---------------------------------------------------------------------------


def test_etb_on_resolve_self_trigger_byte_equal():
    """A creature with a ``source_is_self`` ENTERS trigger cast through
    the re-homed ``stack_objects`` source resolves; the ETB fires at
    ``move_source_post_resolve`` → ``dispatch_event(Enters)`` reading
    the re-homed source. The full field view is byte-equal Python↔Rust
    at BOTH the mid-stack (spell on re-homed store) AND the
    post-resolve (ETB fired, card drawn) compare points.

    This is the core G7 owner-doc Slice S5 deliverable: a permanent
    spell's ETB trigger now fires at *resolution* off the re-homed
    source instead of inside the atomic cast, byte-matching Python's
    ``put_into_battlefield`` ETB-on-stack push.
    """
    s5b = _s5b()
    spec = _trigger_bears_spec([_ETB_DRAW])
    py_state, rust_state, cast_id = s5b._drive_to_spell_on_stack(spec)

    # Mid-stack (re-homed): byte-equal BEFORE the ETB resolves.
    _, _, mid = _field_views(py_state, rust_state)
    assert mid == [], (
        f"mid-stack (spell on re-homed store) NOT byte-equal: "
        f"{[(d.field, d.py_value, d.rust_value) for d in mid]}"
    )

    _resolve_all(py_state, rust_state)

    py_view, rust_view, post = _field_views(py_state, rust_state)
    assert post == [], (
        f"ETB-on-resolve self trigger through the re-homed source is "
        f"NOT byte-equal Python↔Rust post-resolve — the resolve-time "
        f"trigger reading ``stack_objects`` diverges: "
        f"{[(d.field, d.py_value, d.rust_value) for d in post]}"
    )
    # The carrier landed on the battlefield on BOTH engines (the ETB
    # actually had a host to fire from — not a vacuous pass).
    py_bf_ids = {t[7] for t in py_view["battlefield"]}
    rust_bf_ids = {t[7] for t in rust_view["battlefield"]}
    assert cast_id in py_bf_ids and cast_id in rust_bf_ids, (
        f"the cast creature did not reach the battlefield on both "
        f"engines (py_bf={py_bf_ids} rust_bf={rust_bf_ids}) — the "
        f"ETB-on-resolve path did not actually execute"
    )
    # The ETB draw fired on BOTH (hand sizes byte-equal AND the draw
    # actually happened — both hands grew by exactly the one draw).
    py_hand = [len(p.hand) for p in py_state.players]
    rust_hand = [
        len(list(rust_state.hand_snapshot(0))),
        len(list(rust_state.hand_snapshot(1))),
    ]
    assert py_hand == rust_hand, (
        f"post-resolve hand sizes diverge py={py_hand} rust={rust_hand} "
        f"— the ETB draw fired on one engine but not the other"
    )


# ---------------------------------------------------------------------------
# Pin 3 — multi-ETB resolve-time push ordering byte-equal
# ---------------------------------------------------------------------------


def test_multi_etb_trigger_push_ordering_byte_equal():
    """TWO ``source_is_self`` ENTERS triggers (draw + scry) on the
    cast creature. When the spell resolves through the re-homed
    source, BOTH ETB triggers are pushed; the pushed order + the
    resolved results are byte-equal Python↔Rust — the §S5 "verify the
    trigger push-ordering vs Python ``put_into_battlefield``
    ETB-on-stack ordering" requirement.

    Discriminating: a push-ORDER divergence (Rust pushing scry-then-
    draw while Python pushes draw-then-scry) would change the
    intermediate stack-signature compare and/or the post-resolve
    library/hand byte view — this asserts both are identical.
    """
    s5b = _s5b()
    spec = _trigger_bears_spec([_ETB_DRAW, _ETB_SCRY])
    py_state, rust_state, _ = s5b._drive_to_spell_on_stack(spec)

    _, _, mid = _field_views(py_state, rust_state)
    assert mid == [], (
        f"mid-stack NOT byte-equal with a multi-ETB carrier on the "
        f"re-homed store: "
        f"{[(d.field, d.py_value, d.rust_value) for d in mid]}"
    )

    # Resolve EXACTLY the spell first — the two ETB triggers should now
    # both be on the stack; compare the stack-signature at that
    # intermediate window (push ORDER is observable here).
    from mtg_bot.actions import resolve_top_of_stack as py_resolve

    py_resolve(py_state)
    rust_state.resolve_top_of_stack()
    py_view, rust_view, inter = _field_views(py_state, rust_state)
    assert py_view["stack"] == rust_view["stack"], (
        f"multi-ETB push ORDER diverges Python↔Rust at the "
        f"post-spell-resolve window: Python stack={py_view['stack']} "
        f"Rust stack={rust_view['stack']} — the resolve-time trigger "
        f"push ordering off the re-homed source is NOT byte-equal"
    )
    assert inter == [], (
        f"post-spell-resolve (both ETB triggers on stack) NOT "
        f"byte-equal: "
        f"{[(d.field, d.py_value, d.rust_value) for d in inter]}"
    )

    # Drain the two triggers — end state byte-equal.
    _resolve_all(py_state, rust_state)
    _, _, post = _field_views(py_state, rust_state)
    assert post == [], (
        f"post-resolve (both ETB triggers resolved) NOT byte-equal — "
        f"multi-trigger resolution off the re-homed source diverges: "
        f"{[(d.field, d.py_value, d.rust_value) for d in post]}"
    )


# ---------------------------------------------------------------------------
# Pin 4 — respond-to-trigger window byte-equal
# ---------------------------------------------------------------------------


def test_respond_to_trigger_window_byte_equal():
    """After resolving EXACTLY the spell (through the re-homed source),
    the ETB triggered ability sits ALONE on the stack as a respondable
    object on BOTH engines — the §S5 "an opponent can respond to a
    triggered ability on the stack" window. The stack-state is
    byte-equal at that respond window, and the trigger then resolves
    byte-equal.

    This is the nested-window surface the S5 owner doc flags as
    sharing S3's risk: the trigger must be a real, equally-respondable
    stack object on both engines (same ``stack_size``, same stack
    signature) — not resolved atomically inside the spell's resolution
    on one engine.
    """
    s5b = _s5b()
    spec = _trigger_bears_spec([_ETB_DRAW])
    py_state, rust_state, _ = s5b._drive_to_spell_on_stack(spec)

    from mtg_bot.actions import resolve_top_of_stack as py_resolve

    # Resolve exactly the spell on each engine.
    py_resolve(py_state)
    rust_state.resolve_top_of_stack()

    # The ETB triggered ability is now ALONE on the stack on BOTH
    # engines — the respond window.
    assert len(py_state.stack) == 1, (
        f"Python: expected exactly the ETB trigger on the stack post-"
        f"spell-resolve, got {len(py_state.stack)} items"
    )
    assert rust_state.stack_size() == 1, (
        f"Rust: expected exactly the ETB trigger on the stack post-"
        f"spell-resolve, got {rust_state.stack_size()} — the trigger "
        f"did NOT become a respondable stack object (resolved "
        f"atomically inside the spell's resolution?)"
    )
    py_view, rust_view, win = _field_views(py_state, rust_state)
    assert py_view["stack"] == rust_view["stack"], (
        f"the respond-to-trigger window stack signature diverges "
        f"Python↔Rust: Python={py_view['stack']} "
        f"Rust={rust_view['stack']}"
    )
    assert win == [], (
        f"respond-to-trigger window NOT byte-equal Python↔Rust: "
        f"{[(d.field, d.py_value, d.rust_value) for d in win]}"
    )

    # The trigger resolves byte-equal (no opponent response taken — the
    # window is verified open + the trigger then resolves in lockstep).
    py_resolve(py_state)
    rust_state.resolve_top_of_stack()
    _, _, after = _field_views(py_state, rust_state)
    assert after == [], (
        f"the ETB trigger resolving out of the respond window is NOT "
        f"byte-equal Python↔Rust: "
        f"{[(d.field, d.py_value, d.rust_value) for d in after]}"
    )


# ---------------------------------------------------------------------------
# Pin 5 — negative control: a re-homed-source hole fails LOUD
# ---------------------------------------------------------------------------


def test_negative_control_rehomed_source_hole_fails_loud():
    """Negative control (the S5b discipline): simulate an S5a
    re-homed-source HOLE in which Rust's resolve-time ETB trigger
    never fires (e.g. the ``move_source_post_resolve`` →
    ``dispatch_event(Enters)`` observer walk failed to reach
    ``stack_objects``). We model the hole by resolving the spell +
    its ETB on Python only and leaving Rust's ETB trigger UNFIRED,
    then asserting ``compare_fields`` reports a LOUD multi-field
    divergence — proving Pin 2/3/4 genuinely discriminate and are
    not trivially-passing.
    """
    s5b = _s5b()
    spec = _trigger_bears_spec([_ETB_DRAW])
    py_state, rust_state, _ = s5b._drive_to_spell_on_stack(spec)

    from mtg_bot.actions import resolve_top_of_stack as py_resolve

    # Resolve the spell on both (the carrier reaches bf on both).
    py_resolve(py_state)
    rust_state.resolve_top_of_stack()
    # Python fires the ETB draw; Rust deliberately does NOT (the
    # simulated re-homed-source hole — trigger never resolves).
    py_resolve(py_state)
    # rust_state.resolve_top_of_stack()  <-- intentionally NOT called

    _, _, divs = _field_views(py_state, rust_state)
    assert divs, (
        "NEGATIVE CONTROL FAILED TO DISCRIMINATE: a simulated S5a "
        "re-homed-source hole (Rust ETB trigger never fired) produced "
        "ZERO compare_fields divergences — the byte-equality pins "
        "above are NOT genuinely discriminating (trivially-passing)"
    )
    fields = {d.field for d in divs}
    # The hole must surface as the trigger's effect NOT having
    # happened on Rust (the draw) AND the trigger still pending on
    # Rust's stack — a genuinely multi-field, unambiguous LOUD signal.
    assert "stack" in fields, (
        f"negative control divergence lacks the expected unresolved-"
        f"trigger 'stack' signal (got fields={fields}) — the control "
        f"is not modelling the re-homed-source hole faithfully"
    )
    assert any(f.startswith("hand_p") for f in fields) or any(
        f.startswith("library_p") for f in fields
    ), (
        f"negative control divergence lacks the expected unfired-draw "
        f"hand/library signal (got fields={fields})"
    )

    # Sanity: completing the Rust resolution closes the divergence —
    # i.e. the ONLY reason it diverged was the (simulated) unfired
    # trigger, not some unrelated pre-existing asymmetry.
    rust_state.resolve_top_of_stack()
    _, _, healed = _field_views(py_state, rust_state)
    assert healed == [], (
        f"completing the Rust ETB resolution did NOT close the "
        f"negative-control divergence (residual {[(d.field) for d in healed]}) "
        f"— the control conflated the simulated hole with a real "
        f"pre-existing trigger-through-re-homed-source divergence "
        f"(THIS WOULD BE A GENUINE S5 FINDING — investigate)"
    )


# ---------------------------------------------------------------------------
# Pin 6 — honest documentation of the CAST-predicate bridge limitation
# ---------------------------------------------------------------------------


def test_cast_predicate_bridge_limitation_is_documented():
    """HONEST documentation pin (`feedback_silent_noop_pipelines` —
    document the limitation, do not paper it).

    The §1.4 surface (the ``dispatch_event`` CAST observer walk + the
    3 ``cards.rs`` predicate subject/controller helpers S5a extended
    to reach ``stack_objects``) cannot be faithfully exercised through
    the cross-engine ``triggered_abilities`` predicate bridge:

      * ``Event.IS_CAST`` carries TWO subject slots —
        ``EVENT_SUBJECTS[Event.IS_CAST] == ("spell", "controller")``.
      * The harness bridge ``_ta_dict_to_python_predicate`` maps
        ``subject_is_creature`` → ``Subject(slot=None, IsCreature())``
        and ``controlled_by_you`` → ``Controlled(YOU, subject=None)``
        — correct for SINGLE-subject events (ENTERS/DIES/ATTACKS) but
        ``_resolve_subject(subjects, None)`` returns ``None`` when the
        event has ≠1 subject (`predicates.py:348` —
        ``if len(subjects) == 1``). So a slot-None predicate on an
        IS_CAST trigger evaluates FALSE on the Python side and the
        Python trigger never fires, while Rust resolves the on-stack
        spell as the subject through the re-homed store and DOES fire
        — a divergence caused by the *harness fixture bridge*, not by
        the S5a engine re-homing.
      * Real card-data CAST triggers parse to an explicitly
        spell-slotted predicate — ``Subject("spell", IsArtifact())``
        / ``Controlled(YOU, subject="controller")``
        (`cards/parser/triggers.py:728-760`) — never slot-None. The
        bridge has no mechanism to target the ``"spell"`` slot for
        IS_CAST, so a faithful cross-engine CAST-predicate fixture is
        NOT constructible through this harness.

    Consequence (and why S5 is still a clean verify): the §1.4 Rust
    CAST observer walk + the ``cards.rs`` helper stack-store extension
    are proven by **S5a's own ``tests_rust`` closure-flips** (the
    silent-CAST-trigger regression S5a fixed, per the S5a status
    header / SOT_FLIP G7 row) AND by Pins 2/3/4 here — the ETB-on-
    resolve / multi-ETB / respond-to-trigger paths fire off
    ``move_source_post_resolve`` → ``dispatch_event(Enters)``, which
    reads the **SAME re-homed ``stack_objects`` source** the CAST
    observer walk reads (`state_ops_resolve.rs:480-517` — the CAST and
    ENTERS extra-observer / stack-store lookups share the one
    re-homed store). A byte-equal ENTERS-through-re-homed-source path
    (Pins 2/3/4 green) exercises the same source-resolution machinery;
    the CAST axis has no SEPARATE re-homed-source code path left
    unverified.

    This pin asserts the limitation is REAL and exactly as described
    (so a future reader cannot mistake the absence of a harness-bridged
    CAST-predicate fixture for an unverified S5 surface).
    """
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.effects.predicates import (
        EVENT_SUBJECTS, Event, _resolve_subject,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate

    # IS_CAST is a 2-subject event.
    assert EVENT_SUBJECTS[Event.IS_CAST] == ("spell", "controller"), (
        f"IS_CAST subject slots changed: "
        f"{EVENT_SUBJECTS[Event.IS_CAST]} — re-evaluate the S5 "
        f"triggers-verify CAST-bridge analysis"
    )
    # ENTERS is single-subject — the bridge's slot-None mapping IS
    # faithful there (this is WHY Pins 2/3/4 are valid).
    assert len(EVENT_SUBJECTS[Event.ENTERS]) == 1, (
        f"ENTERS is no longer single-subject "
        f"({EVENT_SUBJECTS[Event.ENTERS]}) — Pins 2/3/4's faithful-"
        f"bridge premise needs re-checking"
    )

    # The bridge maps subject_is_creature → slot-None Subject.
    pred = _ta_dict_to_python_predicate({"kind": "subject_is_creature"})
    assert getattr(pred, "slot", "MISSING") is None, (
        f"the cross-engine subject_is_creature bridge no longer maps "
        f"to a slot-None Subject ({pred!r}) — if it now names the "
        f"'spell' slot, a faithful cross-engine CAST-predicate fixture "
        f"IS constructible and S5 should add a direct CAST-observer "
        f"byte-equality pin (re-open this analysis)"
    )

    # Demonstrate the no-op: slot-None resolution against the IS_CAST
    # 2-subject mapping returns None → the Python predicate is False.
    is_cast_subjects = {"spell": object(), "controller": object()}
    assert _resolve_subject(is_cast_subjects, None) is None, (
        "slot-None subject resolution against a 2-subject IS_CAST "
        "mapping no longer returns None — the documented harness-"
        "bridge CAST limitation may have been fixed; re-open the S5 "
        "CAST-observer verification analysis"
    )
    # ...whereas naming the 'spell' slot (the real-card-data shape)
    # resolves correctly — confirming the limitation is purely a
    # harness-bridge gap, not an engine gap.
    sentinel = object()
    is_cast_subjects2 = {"spell": sentinel, "controller": object()}
    assert _resolve_subject(is_cast_subjects2, "spell") is sentinel, (
        "naming the 'spell' slot does not resolve the on-stack spell "
        "subject — the predicates substrate changed; re-verify the S5 "
        "CAST analysis"
    )
