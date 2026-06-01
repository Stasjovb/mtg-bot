"""Cross-engine parity probes for Nexus of Fate (BLOCKED -> PROBED).

**The extra-turn-clause Effect substrate (2026-05-31).** Nexus of Fate
``{5}{U}{U}`` Instant (Special Guests reprint in the EoE pool):

    "Take an extra turn after this one. If Nexus of Fate would be put
    into a graveyard from anywhere, instead shuffle it into its owner's
    library."

Nexus had TWO gates and BOTH are now closed:

  * **Clause 2 — the shuffle-self redirect static** (``WOULD_GO_TO_
    GRAVEYARD -> Replace(new_destination="library")``). Closed by the
    Green Sun's Zenith flip (``test_green_suns_zenith_parity.py``,
    2026-05-31): the Rust ``move_source_post_resolve`` hook reroutes a
    resolving spell whose printing carries that StaticReplacement to its
    owner's library + shuffles, mirroring Python's
    ``_send_to_graveyard_or_library``. Nexus shares the IDENTICAL static
    with GSZ, so the redirect side was already cross-engine byte-equal
    (GSZ puts its fetched creature third-from-… no — GSZ's fetch is a
    SEPARATE library search; the SPELL-SELF redirect on resolve is the
    same shuffle-into-library reroute for both cards. The shuffle-vs-
    position distinction never arises for the spell-self redirect: both
    cards shuffle their OWN card into the owner's library on resolve).

  * **Clause 1 — the extra-turn clause** (``TakeExtraTurnAfterThisOne``).
    This lane lands the genuinely-missing piece. The Python effect
    ``effects.generic.stack_control.TakeExtraTurnAfterThisOne`` (a
    field-free frozen dataclass appending the controller to
    ``state.extra_turn_queue``) had NO Rust mirror. This lane adds:

      * Rust ``Effect::TakeExtraTurnAfterThisOne`` unit variant + parse
        arm + ``to_pydict`` arm + resolve arm (appends the resolving
        spell's controller to a new ``GameState.extra_turn_queue``
        ``Vec<u8>`` field, surfaced via the ``extra_turn_queue()``
        getter).
      * The ``take_extra_turn_after_this_one`` dict->Python bridge arm
        + the reverse-serializer leaf in
        ``trajectory._python_spell_effect_to_dict``.

    This makes ``TakeExtraTurnAfterThisOne`` a covered+bridged class
    (the ``effect_coverage.covered_python_class_set()`` 1:1 identity
    mapping). Combined with the already-bridged redirect static, Nexus
    of Fate ADMITS at the spell-card-bridge gate and flips to PROBED.

**Parity is NOT search (the accepted divergence).** Extra turns were
historically "declined" because they explode the AI SEARCH tree. That
is SEPARATE from cross-engine PARITY. For a byte-equal PROBE both
engines only need to model the extra-turn QUEUE state identically: cast
Nexus -> resolve -> both engines append exactly one controller id to
their extra-turn queue, byte-equal. The Rust turn-advance does NOT pop
this queue — the AI search does not actually take the queued extra
turn. That accepted parity-vs-search divergence is documented in
``docs/SEARCH_LIMITATIONS.md``.
"""

from __future__ import annotations

import importlib.util

import pytest


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_nexus_spell_effect_and_redirect_static():
    """**Verify-first.** The live parser maps Nexus of Fate to a
    ``TakeExtraTurnAfterThisOne`` spell_effect ({5}{U}{U} Instant) AND
    carries the shuffle-self ``WOULD_GO_TO_GRAVEYARD -> library``
    ReplacementEffect static (shared with Green Sun's Zenith).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.stack_control import (
        TakeExtraTurnAfterThisOne,
    )
    from mtg_bot.effects.modifiers import (
        EventPattern, Replace, ReplacementEffect,
    )
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("Nexus of Fate")
    if p is None:
        pytest.skip("Nexus of Fate absent from active CardSource")
    assert p.is_instant
    assert p.mana_cost_str == "{5}{U}{U}"
    assert isinstance(p.spell_effect, TakeExtraTurnAfterThisOne)
    # The shuffle-self static (shared with GSZ — the clause-2 redirect).
    expected_static = ReplacementEffect(
        event_pattern=EventPattern(event=Event.WOULD_GO_TO_GRAVEYARD),
        transform=Replace(new_destination="library"),
    )
    assert any(
        s.replacement_effect == expected_static
        for s in p.static_abilities
    ), "Nexus must carry the shuffle-self WOULD_GO_TO_GRAVEYARD->library static"


# -------------------------------------------------------------------
# Coverage + round-trip pins (the substrate this lane lands).
# -------------------------------------------------------------------


def test_take_extra_turn_effect_class_covered():
    """The Rust ``Effect::TakeExtraTurnAfterThisOne`` variant makes the
    Python class covered (1:1 identity mapping)."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "TakeExtraTurnAfterThisOne" in covered, (
        "Rust Effect variant must make the Python class covered"
    )


def test_take_extra_turn_serializer_round_trip():
    """The reverse serializer emits the kind-only unit dict; the
    dict->Python bridge reconstructs the field-free effect."""
    from mtg_bot.effects.generic.stack_control import (
        TakeExtraTurnAfterThisOne,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = TakeExtraTurnAfterThisOne()
    d = trajectory._python_spell_effect_to_dict(eff)
    assert d == {"kind": "take_extra_turn_after_this_one"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, TakeExtraTurnAfterThisOne)


def test_nexus_admits_at_bridge_gate_after_extra_turn_substrate():
    """**The flip pin.** With both gates closed — the
    ``would_go_to_graveyard -> library`` redirect static bridged (GSZ
    flip) AND the ``TakeExtraTurnAfterThisOne`` spell_effect now
    covered+bridged (this lane) — Nexus of Fate ADMITS at the
    spell-card-bridge gate.

    This is the inverse of the prior decline pin in
    ``test_green_suns_zenith_parity.py``
    (``test_gsz_redirect_widen_keeps_nexus_and_quantum_riddler_declined``):
    Nexus stays declined there ONLY because the extra-turn substrate is
    unbuilt. With it built, Nexus is genuinely probe-able (see the
    real-EoE byte-equal probe below).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Nexus of Fate")
    if p is None:
        pytest.skip("Nexus of Fate absent from active CardSource")
    # The spell_effect side is now covered+bridged.
    assert trajectory._spell_effect_is_covered_and_bridged(p) is True
    assert (
        trajectory._python_spell_effect_to_dict(p.spell_effect) is not None
    )
    # The shuffle-self redirect static is bridgeable (shared with GSZ).
    assert (
        trajectory._printing_has_unbridgeable_replacement_static(p) is False
    ), "Nexus's graveyard->library redirect is bridgeable (GSZ flip)"
    # And the card admits at the spell-card-bridge gate.
    assert trajectory._printing_is_bridge_simple_spell(p) is True, (
        "Nexus of Fate must ADMIT post-extra-turn-substrate"
    )
    # The replacement quad the bridge threads through to the CardDef.
    reps = trajectory._static_replacements_from_printing(p)
    assert reps == (
        ("would_go_to_graveyard", "replace", 0, "library"),
    ), f"Nexus redirect must round-trip as the replace quad; got {reps}"


# -------------------------------------------------------------------
# Rust resolve-arm pins (synthetic state — queue append + redirect).
# -------------------------------------------------------------------


_ZONE_GRAVEYARD = 3


def _build_rust_nexus_state():
    """Build a Rust state with the bridged Nexus carrier (genuine
    effect-kind + the would_go_to_graveyard->library redirect static) on
    p0's stack. Returns ``(rs, spell_id)``."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    spell_id = rs.register_and_inject_object(
        {
            "name": "Nexus of Fate",
            "card_types": ["Instant"],
            "effects": [{"kind": "take_extra_turn_after_this_one"}],
            "static_replacements": [
                {
                    "event": "would_go_to_graveyard",
                    "transform_kind": "replace",
                    "transform_dest": "library",
                }
            ],
        },
        0,
        0,
    )
    rs.push_to_stack(spell_id, 0)
    return rs, spell_id


@_rust_skip
def test_rust_nexus_queues_extra_turn_for_controller():
    """The Rust ``Effect::TakeExtraTurnAfterThisOne`` resolve arm appends
    the resolving spell's controller (p0) to ``state.extra_turn_queue``,
    surfaced via the ``extra_turn_queue()`` getter."""
    rs, _spell_id = _build_rust_nexus_state()
    assert list(rs.extra_turn_queue()) == [], "queue starts empty"
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    assert list(rs.extra_turn_queue()) == [0], (
        "Nexus must queue exactly one extra turn for its controller (p0)"
    )


@_rust_skip
def test_rust_nexus_shuffles_self_into_library():
    """The redirect-hook side (clause 2): the resolving Nexus is
    rerouted to p0's LIBRARY (not the graveyard) by the Rust
    ``move_source_post_resolve`` hook (the shuffle-self redirect shared
    with Green Sun's Zenith)."""
    rs, spell_id = _build_rust_nexus_state()
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    lib_ids = {e["id"] for e in rs.library_snapshot(0)}
    gy_ids = {e["id"] for e in rs.graveyard_snapshot(0)}
    assert spell_id in lib_ids, (
        "Nexus must be redirected into its owner's library by the "
        "would_go_to_graveyard->library StaticReplacement"
    )
    assert spell_id not in gy_ids, "Nexus must NOT be in the graveyard"


@_rust_skip
def test_rust_instant_without_extra_turn_effect_does_not_queue():
    """Control: a resolving Instant WITHOUT the extra-turn effect leaves
    the queue empty (the queue is touched only by the
    ``TakeExtraTurnAfterThisOne`` arm)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    spell_id = rs.register_and_inject_object(
        {
            "name": "Plain Instant",
            "card_types": ["Instant"],
            "effects": [{"kind": "draw_cards", "count": 1}],
        },
        0,
        0,
    )
    rs.push_to_stack(spell_id, 0)
    rs.resolve_top_of_stack()
    assert list(rs.extra_turn_queue()) == [], (
        "a non-extra-turn Instant must not touch the extra-turn queue"
    )


# -------------------------------------------------------------------
# GENUINE real-printing cross-engine PROBE (the PROBED-tier flip).
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_nexus_of_fate_extra_turn_and_shuffle_parity():
    """**GENUINE real-printing cross-engine probe — Nexus of Fate.
    PROBED-tier flip (BLOCKED -> PROBED).**

    Drives the **ACTUAL parsed Nexus of Fate printing** on the Python
    side: ``get_active_source().get_printings()["Nexus of Fate"]`` —
    which the live parser maps to a ``spell_effect`` of
    ``TakeExtraTurnAfterThisOne()`` (verified above) AND the shuffle-self
    ``WOULD_GO_TO_GRAVEYARD -> Replace(new_destination="library")``
    ``StaticReplacement`` static.

    Oracle (``data/edge_of_eternities.json``): "[Instant] {5}{U}{U} —
    Take an extra turn after this one. If Nexus of Fate would be put
    into a graveyard from anywhere, instead shuffle it into its owner's
    library."

    **Empty-library config (the byte-equal harness shape).** p0's
    library is EMPTY, so:

      * The clause-1 extra-turn resolve appends p0 to the extra-turn
        queue on BOTH engines (byte-equal — read via Python's
        ``state.extra_turn_queue`` and Rust's ``extra_turn_queue()``
        getter).
      * The clause-2 redirect reroutes Nexus to p0's library; the
        post-redirect shuffle operates on the lone Nexus (``len < 2``) —
        a deterministic no-op.

    So the WHOLE post-resolve field view is deterministic + byte-equal:
    Nexus ends as the SOLE card in p0's LIBRARY (NOT the graveyard) on
    both engines, every other field-view observable matches, AND the
    extra-turn queue holds exactly ``[0]`` on both engines. This is the
    genuine PROBED-tier evidence that BOTH clauses translate byte-equal
    cross-engine.

    **Parity-not-search.** The extra-turn queue is byte-equal; neither
    engine's harness here advances the turn, so the parity-vs-search
    divergence (the Rust turn-advance never pops the queue) is not
    exercised — exactly the byte-equal-queue-state contract the probe
    asserts. Documented in ``docs/SEARCH_LIMITATIONS.md``.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        build_python_field_view,
        compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.stack_control import (
        TakeExtraTurnAfterThisOne,
    )

    real = get_active_source().get_printings().get("Nexus of Fate")
    if real is None:
        pytest.skip("Nexus of Fate absent from active CardSource")
    assert "Instant" in real.card_types
    assert isinstance(real.spell_effect, TakeExtraTurnAfterThisOne)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: cast the genuine Nexus printing.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: push the bridged Nexus carrier (genuine effect-kind +
    # the would_go_to_graveyard->library redirect static), resolve.
    rs_spell = rs.register_and_inject_object(
        {
            "name": "Nexus of Fate",
            "card_types": ["Instant"],
            "effects": [{"kind": "take_extra_turn_after_this_one"}],
            "static_replacements": [
                {
                    "event": "would_go_to_graveyard",
                    "transform_kind": "replace",
                    "transform_dest": "library",
                }
            ],
        },
        0,
        0,
    )
    rs.push_to_stack(rs_spell, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # ---- (a) FULL byte-equal field-view compare (the clause-2
    # library-redirect observable is in FIELD_DIFF_FIELDS).
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Nexus of Fate must be byte-equal across the WHOLE field view "
        f"on BOTH engines; diffs={diffs}"
    )

    # ---- (b) EXTRA-TURN QUEUE byte-equal (clause-1; NOT in the
    # field-view, read via each engine's queue surface).
    assert py.extra_turn_queue == [0], (
        "Python: Nexus must queue exactly one extra turn for p0"
    )
    assert list(rs.extra_turn_queue()) == [0], (
        "Rust: Nexus must queue exactly one extra turn for p0 (byte-equal)"
    )
    assert py.extra_turn_queue == list(rs.extra_turn_queue()), (
        "the extra-turn queue must be byte-equal across engines"
    )

    # ---- Observable cross-checks: Nexus in LIBRARY, not graveyard.
    assert py_spell.zone == Zone.LIBRARY, (
        "Python: Nexus must shuffle itself into the library (not graveyard)"
    )
    assert any(o.id == py_spell.id for o in py.players[0].library)
    assert all(o.id != py_spell.id for o in py.players[0].graveyard)
    rs_lib = {e["id"] for e in rs.library_snapshot(0)}
    rs_gy = {e["id"] for e in rs.graveyard_snapshot(0)}
    assert rs_spell in rs_lib, (
        "Rust: Nexus must shuffle itself into the library (byte-equal)"
    )
    assert rs_spell not in rs_gy
