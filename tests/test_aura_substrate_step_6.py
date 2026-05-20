"""Aura-attachment substrate — Phase 1 STEP 6 tests.

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 1 step 6
(bidirectional bridge round-trip).

**STEP 6 scope.** STEPs 1-5 wired up the aura substrate end-to-end on
each engine:

* STEP 1 — Python ``CardDef`` aura fields + bridge predicate
* STEP 2 — Rust ``CardPrinting`` aura fields + ``parse_printing`` arms
  + four ``Registry.get_printing_aura_*`` getters
* STEP 3 — cast-time enchant-target decision (Rust)
* STEP 4 — Rust Aura resolve arm + layer-7/-6 grants
* STEP 5 — Rust CR-704.5n SBA host-less / illegal-host Aura bury

What was missing — the cross-engine bridge for the **state** plumbing:

1. **Printing aura fields** are emitted Python -> Rust by STEP 1 and
   consumed by STEP 2's parse arm, but the symmetric Rust -> Python
   read-back was never spelled out as a callable helper. STEP 6 adds
   :func:`mtg_bot.parity.cross_engine.read_rust_printing_aura_fields`,
   the Rust-Registry -> Python-dict surfacing of the four getters
   landed by STEP 2 (``get_printing_is_aura`` /
   ``get_printing_aura_enchant_type`` / ``get_printing_aura_yours_only``
   / ``get_printing_aura_grant``).
2. **Bf object ``attached_to``** is already emitted by Rust's
   ``object_to_pydict`` (``state_ops_snapshot.rs:91-94``) and Rust's
   ``fingerprint()`` (``state_ops_fingerprint.rs:155-158``), but the
   Python-side hash recipe in ``scripts/parity_smoke.py:_rust_zone_obj_sig``
   hardcoded ``None`` for the slot (the "Rust doesn't track attached_to
   yet" comment, pre-Round-28). STEP 6 fixes that to read the field
   verbatim from the snapshot dict so the Python-built hash matches both
   Rust's native ``fingerprint()`` AND Python's ``_zone_signature`` for
   any state with an attached object (Equipment + Aura post-STEP-4).

Once STEP 6 lands, STEP 7 (the one-line OR-in of
``_printing_is_bridge_simple_aura`` into the loader's 5-disjunct
admit chokepoint at
``src/mtg_bot/parity/trajectory.py:_filter_deck_to_bridge_supported``)
becomes safe to flip — bench probes can drive Auras cross-engine and
expect byte-equal post-resolve state on both sides.

**Out-of-scope for STEP 6 (kept honest-stops):**

* STEP 7 itself — the loader OR-in. That's the next deliberate step.
* Sub-shape S2 (control-changing auras) bridge work — Phase 2 lane.
* Residue Aura-shape Effects bridge arms — Phase 3 lane.
"""

from __future__ import annotations

import importlib

import pytest

from mtg_bot.parity.cross_engine import (
    CardDef,
    DeckSpec,
    _FOREST,
    _card_def_to_python_printing,
    build_python_state,
    build_rust_registry,
    build_rust_state,
    read_rust_printing_aura_fields,
    rust_bf_object_attached_to,
)


ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _aura_spec(aura_card_def):
    """Smallest possible DeckSpec carrying Forest + the given Aura."""
    return DeckSpec(
        card_defs=(_FOREST, aura_card_def),
        p0_library=("Forest",) * 7,
        p1_library=("Forest",) * 7,
    )


# ---------------------------------------------------------------------------
# Helper: read_rust_printing_aura_fields surfaces the four Rust getters
# ---------------------------------------------------------------------------


def test_read_rust_printing_aura_fields_returns_non_aura_defaults_for_non_aura():
    """For every pre-substrate / non-aura printing, the Rust read-back
    returns the back-compat defaults — bit-identical to what
    ``_card_def_to_python_printing`` materializes from a CardDef with
    ``is_aura=False``."""
    _require_engine()
    spec = DeckSpec(
        card_defs=(_FOREST,),
        p0_library=("Forest",),
        p1_library=("Forest",),
    )
    reg, _ = build_rust_registry(spec)
    fields = read_rust_printing_aura_fields(reg, 0)
    assert fields == {
        "is_aura": False,
        "aura_enchant_type": "creature",
        "aura_yours_only": False,
        "aura_power_bonus": 0,
        "aura_toughness_bonus": 0,
        "aura_granted_keywords": (),
        "equipment_bonuses": None,
    }


def test_read_rust_printing_aura_fields_round_trips_frantic_strength_shape():
    """Frantic Strength shape — ``is_aura=True``,
    ``aura_enchant_type="creature"``, P/T +2/+2, granted ``trample``
    — round-trips Python CardDef -> Rust registry -> Python dict
    byte-equal (modulo frozenset vs tuple keyword storage)."""
    _require_engine()
    cd = CardDef(
        name="Frantic Strength",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_power_bonus=2,
        aura_toughness_bonus=2,
        aura_granted_keywords=("trample",),
    )
    spec = _aura_spec(cd)
    reg, _ = build_rust_registry(spec)
    fields = read_rust_printing_aura_fields(reg, 1)
    assert fields["is_aura"] is True
    assert fields["aura_enchant_type"] == "creature"
    assert fields["aura_yours_only"] is False
    assert fields["aura_power_bonus"] == 2
    assert fields["aura_toughness_bonus"] == 2
    assert fields["aura_granted_keywords"] == ("trample",)
    assert fields["equipment_bonuses"] == (2, 2, frozenset({"trample"}))


def test_read_rust_printing_aura_fields_round_trips_shardmage_rescue_shape():
    """Shardmage's Rescue shape — ``aura_yours_only=True`` + +1/+1, no
    granted keyword. Round-trips with ``aura_yours_only=True`` preserved
    AND the empty-keyword grant tuple."""
    _require_engine()
    cd = CardDef(
        name="Shardmage's Rescue",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("W", 1),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_yours_only=True,
        aura_power_bonus=1,
        aura_toughness_bonus=1,
    )
    spec = _aura_spec(cd)
    reg, _ = build_rust_registry(spec)
    fields = read_rust_printing_aura_fields(reg, 1)
    assert fields["is_aura"] is True
    assert fields["aura_yours_only"] is True
    assert fields["aura_power_bonus"] == 1
    assert fields["aura_toughness_bonus"] == 1
    assert fields["aura_granted_keywords"] == ()
    assert fields["equipment_bonuses"] == (1, 1, frozenset())


def test_read_rust_printing_aura_fields_artifact_enchant_type():
    """An Aura with ``aura_enchant_type="artifact"`` round-trips
    Python -> Rust -> Python correctly. Validates the
    ``aura_enchant_type`` getter for the non-default branch."""
    _require_engine()
    cd = CardDef(
        name="Synthetic Artifact Aura",
        card_type="Enchantment",
        mana_cost_generic=2,
        is_aura=True,
        aura_enchant_type="artifact",
    )
    spec = _aura_spec(cd)
    reg, _ = build_rust_registry(spec)
    fields = read_rust_printing_aura_fields(reg, 1)
    assert fields["is_aura"] is True
    assert fields["aura_enchant_type"] == "artifact"
    # Bare aura with no bonus/grant -> equipment_bonuses None.
    assert fields["equipment_bonuses"] is None


def test_read_rust_printing_aura_fields_keyword_with_space_round_trips():
    """A granted keyword with spaces (``first strike``) is emitted
    underscore-form by the bridge; the Rust read-back surfaces it in
    the same underscore-form (no inverse transform). Pins the bridge
    convention (Python's space-separated -> Rust's underscore-form,
    unchanged on the way back) at the aura layer."""
    _require_engine()
    cd = CardDef(
        name="Synthetic Multi-Keyword Aura",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("W", 1),),
        is_aura=True,
        aura_granted_keywords=("first strike", "vigilance"),
    )
    spec = _aura_spec(cd)
    reg, _ = build_rust_registry(spec)
    fields = read_rust_printing_aura_fields(reg, 1)
    # Underscore form on the Rust side; order is preserved.
    assert set(fields["aura_granted_keywords"]) == {"first_strike", "vigilance"}
    assert fields["equipment_bonuses"] is not None
    assert fields["equipment_bonuses"][2] == frozenset(
        {"first_strike", "vigilance"}
    )


def test_aura_printing_fields_match_python_carddef_to_printing_round_trip():
    """The Rust-side read-back of an Aura printing MATCHES the
    Python-side ``_card_def_to_python_printing`` materialization on
    every aura slot. Pins the cross-engine bridge symmetry: from ONE
    CardDef, BOTH sides produce the same aura representation."""
    _require_engine()
    cd = CardDef(
        name="Frantic Strength",
        card_type="Enchantment",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_power_bonus=2,
        aura_toughness_bonus=2,
        aura_granted_keywords=("trample",),
    )
    spec = _aura_spec(cd)
    reg, _ = build_rust_registry(spec)
    rust_fields = read_rust_printing_aura_fields(reg, 1)

    py_pr = _card_def_to_python_printing(cd)
    assert rust_fields["is_aura"] == py_pr.is_aura
    assert rust_fields["aura_enchant_type"] == py_pr.aura_enchant_type
    assert rust_fields["aura_yours_only"] == py_pr.aura_yours_only
    assert rust_fields["equipment_bonuses"] == py_pr.equipment_bonuses


# ---------------------------------------------------------------------------
# Bf-object attached_to round-trips through battlefield_snapshot
# ---------------------------------------------------------------------------


def _aura_printing_dict(
    name="Frantic Strength",
    mana_cost=None,
    enchant_type="creature",
    yours_only=False,
    p_bonus=2,
    t_bonus=2,
    granted_keywords=("trample",),
):
    """Build a registry-dict for an Aura printing. Mirrors the
    STEP-2/4 emission shape."""
    if mana_cost is None:
        mana_cost = {"R": 1}
    d = {
        "name": name,
        "mana_cost": mana_cost,
        "card_types": ["Enchantment"],
        "subtypes": ["Aura"],
        "is_aura": True,
        "aura_enchant_type": enchant_type,
    }
    if yours_only:
        d["aura_yours_only"] = True
    if p_bonus or t_bonus or granted_keywords:
        d["aura_equipment_bonuses"] = {
            "power_bonus": p_bonus,
            "toughness_bonus": t_bonus,
            "granted_keywords": list(granted_keywords),
        }
    return d


def _creature_dict(name="Grizzly Bears", power=2, toughness=2):
    return {
        "name": name,
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "power": power,
        "toughness": toughness,
    }


def _fresh_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def test_unattached_bf_object_round_trips_attached_to_as_none():
    """An object on the battlefield that has never been attached
    surfaces ``attached_to == None`` through ``battlefield_snapshot``
    and through the :func:`rust_bf_object_attached_to` helper. Pins
    the back-compat default — the universal pre-STEP-6 invariant.
    """
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    # Direct dict access via the snapshot.
    bf = [o for o in state.battlefield_snapshot() if o["id"] == bears_id]
    assert len(bf) == 1
    assert bf[0]["attached_to"] is None
    # The helper agrees.
    assert rust_bf_object_attached_to(state, bears_id) is None


def test_aura_attached_to_round_trips_through_battlefield_snapshot():
    """After an Aura resolves attached to a legal host (STEP 4), the
    ``attached_to`` slot on the bf snapshot dict carries the host id —
    surfacing the same Rust state Python's ``_zone_signature`` would
    read on the Python side."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    state.submit_enchant_target_decision(bears_id)
    state.resolve_top_of_stack()

    bf = state.battlefield_snapshot()
    aura_dicts = [o for o in bf if o["id"] == aura_id]
    assert len(aura_dicts) == 1
    assert aura_dicts[0]["attached_to"] == bears_id

    # Helper agrees.
    assert rust_bf_object_attached_to(state, aura_id) == bears_id
    # The host's own attached_to remains None (only the aura is attached).
    assert rust_bf_object_attached_to(state, bears_id) is None


def test_fizzled_aura_does_not_leave_attached_to_on_graveyard_object():
    """When the Aura fizzles to graveyard (STEP 4 fizzle path: no legal
    target at resolve), the graveyard-side snapshot reports
    ``attached_to=None``. This pins the STEP-5 SBA-bury reset path
    via the bridge's snapshot shape."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    # Note: no host on the battlefield -> cast pushes decision with no
    # candidates -> fizzle on resolve.
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    # If the cast pump pushed a decision with no candidates, the
    # decision queue is empty (STEP 3 dispatch); resolve still fizzles.
    if state.pending_decisions():
        state.submit_enchant_target_decision(None)
    state.resolve_top_of_stack()
    gy = state.graveyard_snapshot(0)
    aura_gy = [o for o in gy if o["id"] == aura_id]
    assert len(aura_gy) == 1
    assert aura_gy[0]["attached_to"] is None


# ---------------------------------------------------------------------------
# Cross-engine: Python's _zone_signature now matches Rust's
# fingerprint() on a state with an attached object
# ---------------------------------------------------------------------------


def test_rust_zone_obj_sig_emits_attached_to_from_snapshot_dict():
    """The Python-side helper :func:`scripts.parity_smoke._rust_zone_obj_sig`
    surfaces the snapshot dict's ``attached_to`` slot directly (pre-STEP-6
    it hardcoded ``None``). Pins the byte-equality between Python's
    fingerprint recipe and Rust's native ``fingerprint()`` when at
    least one bf object carries ``attached_to != None``."""
    _require_engine()
    # Load parity_smoke via the same shim cross_engine uses.
    from mtg_bot.parity.cross_engine import parity_smoke
    ps = parity_smoke()

    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    state.submit_enchant_target_decision(bears_id)
    state.resolve_top_of_stack()

    # Find the aura's snapshot dict and project through _rust_zone_obj_sig.
    aura_dict = next(
        o for o in state.battlefield_snapshot() if o["id"] == aura_id
    )
    sig = ps._rust_zone_obj_sig(aura_dict)
    # The 8-tuple's 6th slot (index 5) is attached_to. Pre-STEP-6 this
    # was hardcoded None; STEP-6 surfaces the actual host id.
    assert sig[5] == bears_id


def test_python_built_hash_recipe_matches_native_fingerprint_for_aura_state():
    """Strongest end-to-end pin for STEP 6 on the state side: the
    Python-built hash recipe (:func:`scripts.parity_smoke._hash_rust_state`)
    matches the native ``state.fingerprint()`` for a state with an
    attached Aura. Pre-STEP-6 the Python recipe blew the equality
    because the ``attached_to`` slot was hardcoded ``None``."""
    _require_engine()
    from mtg_bot.parity.cross_engine import parity_smoke
    ps = parity_smoke()

    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    state.submit_enchant_target_decision(bears_id)
    state.resolve_top_of_stack()

    native_fp = state.fingerprint()
    py_fp = ps._hash_rust_state(state)
    assert native_fp == py_fp


# ---------------------------------------------------------------------------
# Pin: STEP 6 does NOT widen the loader (STEP 7 honest-stop)
# ---------------------------------------------------------------------------


def test_step_6_does_not_admit_any_aura_to_the_bench():
    """Originally a STEP-6 honest-stop sentinel: STEP 6 landed the
    bridge round-trip plumbing only and did NOT OR
    ``_printing_is_bridge_simple_aura`` into the loader. STEP 7
    (round-78) closed that gap, but Frantic Strength still doesn't
    admit because the predicate's §2 teeth decline it (the printing
    carries the non-``_SAFE_KEYWORDS`` ``flash`` keyword — the
    documented decline reason). So this pin still passes, now
    measuring the predicate's §2 correctness rather than the missing
    OR-in. See ``test_aura_substrate_phase1.py``::
    ``test_loader_admits_aura_simple_shape`` for the positive STEP-7
    wire-up pin."""
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported
    from mtg_bot.cards.source import get_active_source
    printings = get_active_source().get_printings()
    deck = ["Forest", "Forest", "Frantic Strength", "Forest"]
    not_bridged_sink: list[str] = []
    filtered, _ = _filter_deck_to_bridge_supported(
        deck,
        printings,
        not_bridged_sink=not_bridged_sink,
    )
    assert "Frantic Strength" not in filtered
    assert "Frantic Strength" in not_bridged_sink


# ---------------------------------------------------------------------------
# rust_bf_object_attached_to: edge cases
# ---------------------------------------------------------------------------


def test_rust_bf_object_attached_to_returns_none_for_unknown_id():
    """The helper returns ``None`` for an id that isn't on any
    battlefield (e.g. the object was sent to graveyard or never
    materialized)."""
    _require_engine()
    state = _fresh_state()
    # Nothing on bf -> any id lookup returns None.
    assert rust_bf_object_attached_to(state, 12345) is None


def test_rust_bf_object_attached_to_returns_int_for_attached_object():
    """The helper coerces the snapshot's ``attached_to`` value to a
    plain int — protects against an int subclass / numpy int leaking
    through the snapshot dict and breaking ``==`` comparisons on the
    consumer side."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    state.submit_enchant_target_decision(bears_id)
    state.resolve_top_of_stack()
    val = rust_bf_object_attached_to(state, aura_id)
    assert isinstance(val, int)
    assert val == bears_id
