"""Swarmyard Carrier-AA Phase 1 Cycle 3 — per-card real-EoE
cross-engine byte-equality probe (``covered_by_construction`` →
PROBED tier flip).

Swarmyard is an EoE ``Land`` carrier with a single bare-``{T}``
activated ability: ``{T}: Regenerate target Rat, Spider, Squirrel,
or Insect`` (live ``OracleParserCardSource`` shape:
``RegenerateTargetCreature(allowed_subtypes=frozenset({'Rat',
'Spider', 'Squirrel', 'Insect'}))``).

**Multi-cycle DECLINED → ADMITTED → PROBED transition.**

  * **Phase 1 Cycle 1 (substrate, commit ``226c9738``,
    2026-05-25).** Rust substrate landing:
    ``CardDef.activated_abilities`` non-token field +
    ``Effect::RegenerateTargetCreature { allowed_subtypes:
    Vec<String> }`` + ``Effect::UntapTargetLand`` (unit) +
    ``GameObject.regeneration_shield: bool`` + cross-engine bridge
    arms + mutual-exclusion guard. Swarmyard stayed DECLINED at the
    bridge admit gate (no admit predicate yet).
  * **Phase 1 Cycle 2 (THE FLIP, commit ``0cc08732``, 2026-05-25).**
    Python bridge admit predicate
    ``_printing_is_bridge_simple_carrier_aa_land`` +
    ``_aa_is_phase1_sub_shape_a`` STRICT bare-``{T}`` gate +
    ``_python_aa_to_safe_dict`` reverse helper +
    ``_carrier_aa_land_card_def`` builder wired into
    ``_filter_deck_to_bridge_supported``'s OR-chain. Swarmyard
    DECLINED → ADMITTED at the production-deck loader filter
    (admit set 0 → +1 — exactly Swarmyard); Deserted Temple stayed
    DECLINED honestly on the STRICT bare-``{T}`` gate (its live
    cost is ``{1}, {T}``, not bare ``{T}``).
  * **Phase 1 Cycle 3 (THIS LANE; THE PROBE).** Per-card real-EoE
    cross-engine byte-equality probe driving BOTH engines through
    the two load-bearing scenarios:

    (a) **Carrier-in-play baseline.** Swarmyard sits on p0's
        battlefield alongside an unwounded Insect-subtype creature
        (Swarmyard's allowed_subtypes filter covers the Insect
        subtype). No SBA fires; the shield is set on the target
        via the test-only ``set_regeneration_shield`` (Python:
        direct attribute write; Rust: the C3-added pymethod).
        Cleanup-step then runs on both engines; the unconsumed
        shield wears off byte-equal (the new C3 cleanup-reset is
        the load-bearing closure for the C1 SL entry's
        "no zone-change reset" failure-mode).

    (b) **Regenerate-the-attacker SBA-consume.** Swarmyard +
        Insect on bf, plus the Insect's damage is pre-raised to
        lethal AND ``regeneration_shield=true`` is pre-set
        (mirroring mid-turn state after a ``{T}: Regenerate target
        creature`` activation resolved against the Insect under
        combat). SBA fires on both engines. The C3-added
        SBA-time consume path catches the regen-eligible victim,
        replaces destruction with the CR 701.15 regenerate
        sequence: ``damage = 0``, ``tapped = true``,
        ``regeneration_shield = false``, drop the id from
        ``attackers`` / ``blockers``. Asserts the Insect is STILL
        on the battlefield on both engines (graveyard empty),
        damage cleared on both, tapped flipped on, shield
        consumed, full field-view byte-equal.

  * **Cycle 3 also wires the additional Rust state-machine
    requirements the C1 SL entry left documented as gaps:**

    1. **SBA-time consume on ``GameObject.regeneration_shield``.**
       The Rust SBA pass at ``state_ops_sba.rs::apply_sbas`` now
       walks the victim list, splits regen-eligible victims (704.5g
       lethal damage only; 704.5f zero-toughness and 704.5i walker
       loyalty stay non-regenerable per CR 701.15) and applies the
       consume in place rather than moving to the graveyard.
       Mirrors Python's ``turn.py:1265-1278`` consume path
       byte-equal.
    2. **Cleanup-step reset on ``GameObject.regeneration_shield``.**
       The Rust ``cleanup_step_for_active_player`` at
       ``state_ops_cleanup.rs`` now drains every shielded
       battlefield permanent's flag back to ``false``. Mirrors
       Python's ``turn.py:1052``
       ``obj.regeneration_shield = False`` blanket clear during
       the CR 514 cleanup pass.

**Pinned by the substrate unit pins below + the two real-EoE
cross-engine probes**. The field-view comparison via
``compare_fields`` does NOT inspect ``regeneration_shield``
directly (it's elided from the per-object 8-tuple per the C1
SL entry's "elided from the per-object fingerprint" convention),
but the SBA-consume's observable effects — damage cleared,
tapped, creature stays on bf, graveyard empty — are all in the
field-view, so a divergence would surface there. The shield bit
itself is asserted byte-equal via direct ``get_regeneration_
shield`` reads on Rust + direct attribute read on Python.

**Real-EoE-signal discipline (round-46).** This module uses the
live ``OracleParserCardSource`` Swarmyard printing — NOT a
synthetic CardDef. The carrier_aa_land_card_def builder at
``trajectory.py::_carrier_aa_land_card_def`` produces the
Python-side CardDef that the bridge round-trips into Rust; the
Rust registry then carries the SAME printing shape both engines
read. The Insect target is a Rats/Spiders/Squirrels/Insects
subtype synthetic CardDef (Swarmyard's allowed_subtypes filter
gates target legality — a Bears target would silently fizzle the
activation, which is NOT what the load-bearing probe pins).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built — mirrors the
# project-wide policy for cross-engine probes.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (Rust int encoding — same shape sibling probes use).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the established pattern in
    sibling per-card parity probes."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# Canonical Rust dict for the Swarmyard carrier — used by the
# rust-parse smoke. Mirrors the wire shape
# ``_spec_card_to_printing_dict`` emits for the C1-substrate
# ``activated_abilities`` non-token field path. The same shape Rust's
# ``register_printing`` accepts on the substrate pin
# ``test_rust_register_carrier_aa_swarmyard_shape``.
_SWARMYARD_RUST_DICT = {
    "name": "Swarmyard",
    "card_types": ["Land"],
    "mana_cost": {},
    "activated_abilities": [
        {
            "cost": {"tap_self": True},
            "effect": {
                "kind": "regenerate_target_creature",
                "allowed_subtypes": [
                    "Insect", "Rat", "Spider", "Squirrel",
                ],
            },
        }
    ],
}


# Synthetic Insect-subtype 2/2 target. Swarmyard's allowed_subtypes
# filter accepts the Insect subtype — the load-bearing C3 scenario
# (b) drives an SBA-consume on a creature this filter would legally
# target. The synthetic shape mirrors the bench convention for
# subtyped creature targets in sibling probes.
_INSECT_BEAR_RUST_DICT = {
    "name": "Test Insect Bear",
    "card_types": ["Creature"],
    "subtypes": ["Insect"],
    "power": 2,
    "toughness": 2,
    "mana_cost": {"generic": 1, "G": 1},
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Swarmyard is parser-claimed and emits the expected
# Phase-1 sub-shape A AA shape (the C1 substrate pin, duplicated here
# so this module is self-contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_swarmyard_parser_claims_card():
    """Pins the active CardSource is producing the Swarmyard printing
    under its canonical EoE name."""
    assert "Swarmyard" in _PRINTINGS, (
        "Swarmyard must be parser-claimed by the active CardSource "
        "(EoE set + reprint coverage)"
    )


def test_swarmyard_printed_attrs():
    """Pins the basic printing surface: ``Land``, no P/T, single AA
    with ``cost.tap_self=True / cost.mana is None``, effect
    ``RegenerateTargetCreature`` with the
    ``{Insect, Rat, Spider, Squirrel}`` allowed-subtypes filter, no
    other riders, no triggered / static, no warp / impending /
    spell_effect / keywords. The C1 substrate pin
    ``test_swarmyard_live_printing_matches_design_doc_shape``
    duplicated to make this module self-contained for the PROBED-tier
    evidence."""
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature

    p = _PRINTINGS["Swarmyard"]
    assert p.card_types == ("Land",)
    assert p.power is None and p.toughness is None
    assert not p.triggered_abilities
    assert not p.static_abilities
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()
    aas = tuple(p.activated_abilities or ())
    assert len(aas) == 1
    aa = aas[0]
    assert aa.cost.tap_self is True
    assert aa.cost.mana is None
    assert aa.cost.sacrifice_self is False
    assert aa.cost.pay_life == 0
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert aa.activate_only_once is False
    assert aa.tier_threshold == 0
    assert aa.room_half is None
    assert aa.cost_reductions == ()
    assert isinstance(aa.effect, RegenerateTargetCreature)
    assert aa.effect.allowed_subtypes == frozenset(
        {"Insect", "Rat", "Spider", "Squirrel"}
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — Python printing → CardDef → Rust dict →
# Python printing round-trips byte-equal on the activated_abilities
# axis. Duplicated from the C2 substrate pin so the per-card module is
# self-contained for the PROBED-tier evidence.
# ---------------------------------------------------------------------------


def test_swarmyard_bridge_round_trip_byte_equal():
    """The C2 admit-gate's bridge: Python printing →
    ``_carrier_aa_land_card_def`` → ``CardDef.activated_abilities``
    tuple → ``_spec_card_to_printing_dict`` Rust dict →
    ``Registry.register_printing`` → ``_card_def_to_python_printing``
    Python printing whose ``activated_abilities`` is byte-equal to the
    live-parsed input."""
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    p_orig = _PRINTINGS["Swarmyard"]
    cd = trajectory._carrier_aa_land_card_def(p_orig)
    assert cd is not None, (
        "Swarmyard must pass the Phase-1 admit predicate per Cycle 2"
    )
    assert cd.card_type == "Land"
    assert cd.activated_abilities  # non-empty tuple
    assert len(cd.activated_abilities) == 1

    # Python reverse arm rematerializes a byte-equal CardPrinting on
    # the activated_abilities axis.
    p_rt = _card_def_to_python_printing(cd)
    assert tuple(p_rt.activated_abilities or ()) == tuple(
        p_orig.activated_abilities or ()
    )
    (aa_rt,) = p_rt.activated_abilities
    assert isinstance(aa_rt.effect, RegenerateTargetCreature)
    assert aa_rt.effect.allowed_subtypes == frozenset(
        {"Insect", "Rat", "Spider", "Squirrel"}
    )


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the Phase-1 Carrier-AA
# ``regenerate_target_creature`` Effect parses on a Swarmyard-shape
# printing via ``register_printing``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_swarmyard_synthetic_dict():
    """Lockstep pin: Rust's parse arm accepts the
    ``{"name": "Swarmyard", "card_types": ["Land"],
       "activated_abilities": [...]}`` payload on a Swarmyard-shape
    synthetic carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_SWARMYARD_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Swarmyard"


# ---------------------------------------------------------------------------
# (4) Substrate unit pin — SBA-time consume mechanic (Rust-side
# in-isolation: a shielded creature with lethal damage stays on the
# battlefield post-``apply_sbas``; damage cleared, tapped, shield
# consumed).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_sba_consume_on_shielded_lethal_damage():
    """Drive Rust's SBA pass on a state with ONE shielded 2/2 carrying
    2 damage (lethal): the C3-added consume path replaces the
    destroy. Pinned: creature stays on bf, damage=0, tapped=true,
    shield=false (consumed). Mirrors Python's
    ``turn.py:1265-1278`` shield-consume gate at the unit-pin level
    (no Swarmyard activation involved — the pin is the SBA-mechanic
    in isolation)."""
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    bear_id = rs.register_and_inject_object(
        _INSECT_BEAR_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    # Mark lethal damage + set the shield. 2 damage on a 2/2 is
    # lethal (704.5g); the shield must intercept.
    assert rs.deal_damage(bear_id, 2) is True
    assert rs.set_regeneration_shield(bear_id, True) is True
    assert rs.get_regeneration_shield(bear_id) is True

    # Apply SBAs. Pre-C3 this would have destroyed the bear.
    rs.apply_sbas()

    # Post-consume observables: still on bf (no graveyard exit),
    # damage cleared, tapped, shield drained.
    bf_ids = [d["id"] for d in rs.battlefield_snapshot()]
    assert bear_id in bf_ids, (
        "Rust: shielded bear with lethal damage must NOT be "
        "destroyed by the SBA — consume replaces the destroy"
    )
    gy_ids_p0 = [d["id"] for d in rs.graveyard_snapshot(0)]
    assert bear_id not in gy_ids_p0, (
        "Rust: shielded bear must NOT have moved to the graveyard"
    )
    bear = next(d for d in rs.battlefield_snapshot() if d["id"] == bear_id)
    assert bear["damage"] == 0, (
        f"Rust: damage must be 0 post-consume; got {bear['damage']}"
    )
    assert bear["tapped"] is True, (
        f"Rust: tapped must be True post-consume; got {bear['tapped']}"
    )
    assert rs.get_regeneration_shield(bear_id) is False, (
        "Rust: shield must be consumed (false) post-SBA"
    )


@_rust_skip
def test_rust_sba_no_consume_on_zero_toughness_shielded():
    """**Honest gate-on-not-zero-toughness pin.** A shielded
    permanent destroyed by 704.5f (zero-toughness, not lethal damage)
    is NOT regenerable per CR 701.15. Mirrors Python's
    ``turn.py:1260-1263`` "tough <= 0 is NOT regeneratable" comment
    + the regen_eligible=false flag the C3-modified
    ``collect_sba_victims`` stamps on 704.5f / 704.5i victims.

    Setup: a 2/2 with TWO -1/-1 counters (effective toughness 0) and
    a shield set. SBA must destroy regardless of the shield."""
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    bear_id = rs.register_and_inject_object(
        _INSECT_BEAR_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    # Stamp -2 net counters: effective toughness = 2 + (-2) = 0 →
    # 704.5f victim, NOT regen-eligible.
    rs.set_counters(bear_id, -2)
    assert rs.set_regeneration_shield(bear_id, True) is True
    rs.apply_sbas()
    bf_ids = [d["id"] for d in rs.battlefield_snapshot()]
    assert bear_id not in bf_ids, (
        "Rust: 0-toughness shielded permanent must STILL be "
        "destroyed (704.5f is NOT regen-eligible per CR 701.15)"
    )
    gy_ids_p0 = [d["id"] for d in rs.graveyard_snapshot(0)]
    assert bear_id in gy_ids_p0


# ---------------------------------------------------------------------------
# (5) Substrate unit pin — cleanup-step reset mechanic (Rust-side
# in-isolation: an unconsumed shield wears off at cleanup).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_cleanup_drains_unconsumed_regeneration_shield():
    """Drive Rust's cleanup-step pass on a state with ONE shielded
    creature at 0 damage: the C3-added cleanup drain clears the
    flag back to false. Pinned: creature stays on bf, shield=false
    post-cleanup, the dict's ``regeneration_shields_cleared`` key
    reports the count. Mirrors Python's ``turn.py:1052``
    ``obj.regeneration_shield = False`` blanket clear."""
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    bear_id = rs.register_and_inject_object(
        _INSECT_BEAR_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    assert rs.set_regeneration_shield(bear_id, True) is True
    summary = rs.cleanup_step_for_active_player()
    assert summary.get("regeneration_shields_cleared") == 1
    assert rs.get_regeneration_shield(bear_id) is False
    bf_ids = [d["id"] for d in rs.battlefield_snapshot()]
    assert bear_id in bf_ids, (
        "Rust: cleanup-step drain must NOT remove the creature — "
        "only its shield flag is cleared"
    )


@_rust_skip
def test_rust_cleanup_zero_count_when_no_shielded_permanents():
    """Cleanup-step on a state with NO shielded permanents reports
    ``regeneration_shields_cleared == 0`` (the CoW-skip arm; no
    ``Arc::make_mut`` clone fires)."""
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    bear_id = rs.register_and_inject_object(
        _INSECT_BEAR_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    assert rs.get_regeneration_shield(bear_id) is False
    summary = rs.cleanup_step_for_active_player()
    assert summary.get("regeneration_shields_cleared") == 0


# ---------------------------------------------------------------------------
# (6) GENUINE real-EoE cross-engine byte-equal probe — Scenario (a):
# carrier-in-play baseline. Swarmyard + Insect creature on p0's
# battlefield; shield set; cleanup runs on both engines; unconsumed
# shield wears off byte-equal. PROBED tier flip evidence (one of two
# scenarios in this Cycle-3 closure marker —
# ``covered_by_construction`` → PROBED).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_swarmyard_baseline_cleanup_drains_shield_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Swarmyard carrier-in-
    play baseline scenario (no SBA fires; cleanup drains the
    unconsumed shield). PROBED tier flip evidence (Cycle 3 closure
    marker, scenario (a) — baseline).**

    Pre-state on both engines:
      * Swarmyard on p0's battlefield (live ``OracleParserCardSource``
        printing on Python; ``_SWARMYARD_RUST_DICT`` on Rust — both
        carry the same name + the same Phase-1 sub-shape A AA dict
        per the C2 bridge round-trip pin).
      * One Insect-subtype 2/2 also on p0's bf (the target of
        Swarmyard's allowed-subtypes filter — the load-bearing
        subtype-overlap case).
      * The Insect carries ``regeneration_shield = True`` (pre-set
        as if a prior ``{T}: Regenerate target creature`` activation
        resolved against it — the test isolates the C3 cleanup-step
        reset from the C2 admit path).

    Drive: ``cleanup_step_for_active_player`` on Rust /
    ``run_cleanup_step`` on Python. Pinned: post-cleanup BOTH engines
    show ``regeneration_shield = False`` on the Insect; the Insect
    is STILL on the battlefield (cleanup is a drain, not a zone
    move); full field-view byte-equal across the whole state.

    The C3 closure marker for the ``cleanup-step reset on shielded
    permanents'' C1 SL entry failure-mode."""
    from mtg_bot.game import Zone
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.turn import run_cleanup_step

    swarmyard_printing = _PRINTINGS.get("Swarmyard")
    if swarmyard_printing is None:
        pytest.skip("Swarmyard absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat Swarmyard + an Insect-bear on p0's bf via the
    # live printing + a synthetic Insect-subtype 2/2 printing. The
    # builder ``new_object`` defaults summoning_sick=True; align with
    # Rust's ``register_and_inject_object`` default of False so the
    # cross-engine field view agrees byte-equal at the per-zone
    # 8-tuple granularity.
    py_swarmyard = py.new_object(
        swarmyard_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_swarmyard.summoning_sick = False
    py_swarmyard.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_swarmyard)

    # Synthetic Insect-bear via the bridge CardDef path. Build the
    # Python CardPrinting via ``_card_def_to_python_printing`` to
    # keep the printing shape byte-equal to the Rust registry
    # (same name, same card_types, same subtypes, no abilities).
    from mtg_bot.parity.cross_engine import (
        CardDef, _card_def_to_python_printing,
    )
    insect_card_def = CardDef(
        name="Test Insect Bear",
        card_type="Creature",
        subtypes=("Insect",),
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    insect_printing = _card_def_to_python_printing(insect_card_def)
    py_insect = py.new_object(
        insect_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_insect.summoning_sick = False
    py_insect.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_insect)
    # Pre-set the shield (mirroring mid-turn state after a prior
    # Swarmyard activation resolved — bypasses the C2 admit path so
    # the probe isolates C3's cleanup-reset mechanic).
    py_insect.regeneration_shield = True

    # ---- Rust: seat the same shapes via register_and_inject_object.
    rs_swarmyard = rs.register_and_inject_object(
        _SWARMYARD_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs_insect = rs.register_and_inject_object(
        _INSECT_BEAR_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    assert rs.set_regeneration_shield(rs_insect, True) is True

    # ---- Pre-cleanup cross-engine field-view sanity. The setup must
    # be byte-equal across engines BEFORE the cleanup fires.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-cleanup baseline setup must be byte-equal across "
        f"engines (Swarmyard + Insect on bf, Insect shielded); "
        f"got pre_diffs={pre_diffs}"
    )

    # Pre-cleanup: shield is set on BOTH engines.
    assert py_insect.regeneration_shield is True
    assert rs.get_regeneration_shield(rs_insect) is True

    # ---- Drive the cleanup on both engines. ----
    run_cleanup_step(py)
    summary = rs.cleanup_step_for_active_player()

    # ---- Post-cleanup observables on both engines: shield drained,
    # creature still on bf, graveyard empty.
    assert py_insect.regeneration_shield is False, (
        "Python: cleanup must drain the unconsumed shield"
    )
    assert rs.get_regeneration_shield(rs_insect) is False, (
        "Rust: cleanup must drain the unconsumed shield"
    )
    assert summary.get("regeneration_shields_cleared") == 1
    assert rs_insect in [
        d["id"] for d in rs.battlefield_snapshot()
    ], "Rust: Insect must STILL be on bf post-cleanup"
    assert py_insect in py.battlefield, (
        "Python: Insect must STILL be on bf post-cleanup"
    )

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Swarmyard baseline scenario (cleanup drains the unconsumed "
        f"shield) must be byte-equal across the WHOLE field view on "
        f"BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (7) GENUINE real-EoE cross-engine byte-equal probe — Scenario (b):
# regenerate-the-attacker SBA-consume. Swarmyard + Insect on p0's
# battlefield; Insect has lethal damage AND shield pre-set; SBA fires
# on both engines; the C3 consume path replaces destroy with
# regenerate sequence byte-equal across engines. PROBED tier flip
# evidence (the LOAD-BEARING scenario in this Cycle-3 closure marker —
# ``covered_by_construction`` → PROBED).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_swarmyard_sba_consume_regenerate_attacker_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Swarmyard
    regenerate-the-attacker SBA-consume scenario. PROBED tier flip
    evidence (Cycle 3 closure marker, scenario (b) — the LOAD-BEARING
    SBA-consume path).**

    THIS is the load-bearing probe: with both engines pre-staged at
    a mid-turn state where Swarmyard's ``{T}: Regenerate target
    creature`` resolved against an Insect attacker that subsequently
    took lethal damage, the SBA pass must REPLACE the destroy with
    the CR 701.15 regenerate sequence byte-equal across engines.

    Pre-state on both engines:
      * Swarmyard on p0's bf (live OracleParserCardSource printing
        on Python; _SWARMYARD_RUST_DICT on Rust).
      * Insect-subtype 2/2 on p0's bf with:
        - ``damage = 2`` (lethal vs. toughness 2 — 704.5g trigger).
        - ``regeneration_shield = True`` (mid-turn shield).
        - The Insect is NOT tapped pre-SBA (the consume must FLIP
          it to tapped, mirroring CR 701.15 "tap it").

    Drive: ``apply_sbas`` on Rust / ``state_based_actions`` on
    Python. Pinned: post-SBA BOTH engines show:
      * Insect STILL on p0's battlefield (consume replaced destroy).
      * Graveyard EMPTY on both players (no creature destroyed).
      * Insect ``damage == 0`` (CR 701.15 "remove all damage").
      * Insect ``tapped == True`` (CR 701.15 "tap it").
      * Insect ``regeneration_shield == False`` (shield consumed —
        the one-shot replacement effect).

    Full ``compare_fields`` byte-equality across the whole state
    (field-view comparison covers per-zone object 8-tuples including
    damage + tapped + the creature's bf membership; the shield bit
    itself is asserted via direct ``get_regeneration_shield`` /
    Python attribute read since the field-view elides the shield
    slot per the C1 SL entry's per-object fingerprint elision)."""
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        _card_def_to_python_printing,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    swarmyard_printing = _PRINTINGS.get("Swarmyard")
    if swarmyard_printing is None:
        pytest.skip("Swarmyard absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat Swarmyard + Insect (lethal damage, shield).
    py_swarmyard = py.new_object(
        swarmyard_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_swarmyard.summoning_sick = False
    py_swarmyard.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_swarmyard)

    insect_card_def = CardDef(
        name="Test Insect Bear",
        card_type="Creature",
        subtypes=("Insect",),
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    insect_printing = _card_def_to_python_printing(insect_card_def)
    py_insect = py.new_object(
        insect_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_insect.summoning_sick = False
    py_insect.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_insect)
    py_insect.damage = 2  # Lethal vs. printed toughness 2.
    py_insect.regeneration_shield = True

    # ---- Rust: seat the same shapes via register_and_inject_object.
    rs_swarmyard = rs.register_and_inject_object(
        _SWARMYARD_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs_insect = rs.register_and_inject_object(
        _INSECT_BEAR_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    assert rs.deal_damage(rs_insect, 2) is True
    assert rs.set_regeneration_shield(rs_insect, True) is True

    # ---- Pre-SBA byte-equal sanity over the WHOLE field view. The
    # field-view 8-tuple covers (printing_name, tapped, summoning_sick,
    # damage, counters, attached_to, controller_id, id) so the
    # pre-SBA state with damage=2 / tapped=false / shield=true (the
    # shield bit is ELIDED from the view) must match across engines.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-SBA setup must be byte-equal across engines "
        f"(Swarmyard + lethal-damaged shielded Insect on bf); "
        f"got pre_diffs={pre_diffs}"
    )
    # Pre-SBA shield + damage on both engines.
    assert py_insect.regeneration_shield is True
    assert py_insect.damage == 2
    assert rs.get_regeneration_shield(rs_insect) is True
    assert rs.get_damage(rs_insect) == 2

    # ---- Drive SBAs on both engines. The C3 consume path is the
    # load-bearing replace-destroy gate.
    py_sba(py)
    rs.apply_sbas()

    # ---- Post-SBA observables on Python.
    # Insect STILL on bf (consume replaced destroy).
    assert py_insect in py.battlefield, (
        "Python: shielded lethal-damaged Insect must STILL be on bf "
        "(consume replaces destroy per CR 701.15)"
    )
    assert py_insect not in py.players[0].graveyard, (
        "Python: shielded Insect must NOT have moved to graveyard"
    )
    assert py_insect.damage == 0, (
        f"Python: damage must be 0 post-consume; got {py_insect.damage}"
    )
    assert py_insect.tapped is True, (
        f"Python: tapped must be True post-consume; got {py_insect.tapped}"
    )
    assert py_insect.regeneration_shield is False, (
        "Python: shield must be consumed (False) post-SBA"
    )

    # ---- Post-SBA observables on Rust.
    rs_bf_ids = [d["id"] for d in rs.battlefield_snapshot()]
    assert rs_insect in rs_bf_ids, (
        "Rust: shielded lethal-damaged Insect must STILL be on bf"
    )
    rs_gy_ids = [d["id"] for d in rs.graveyard_snapshot(0)]
    assert rs_insect not in rs_gy_ids, (
        "Rust: shielded Insect must NOT have moved to graveyard"
    )
    rs_insect_dict = next(
        d for d in rs.battlefield_snapshot() if d["id"] == rs_insect
    )
    assert rs_insect_dict["damage"] == 0, (
        f"Rust: damage must be 0 post-consume; got "
        f"{rs_insect_dict['damage']}"
    )
    assert rs_insect_dict["tapped"] is True, (
        f"Rust: tapped must be True post-consume; got "
        f"{rs_insect_dict['tapped']}"
    )
    assert rs.get_regeneration_shield(rs_insect) is False, (
        "Rust: shield must be consumed (False) post-SBA"
    )

    # ---- Full field-view byte-equality over the WHOLE state.
    # damage cleared, tapped flipped, no zone moves → the per-zone
    # 8-tuples must match exactly on both engines. This is the
    # PROBED-tier load-bearing signal.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Swarmyard SBA-consume scenario must be byte-equal across "
        f"the WHOLE field view on BOTH engines; diffs={diffs}"
    )
