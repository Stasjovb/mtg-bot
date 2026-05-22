"""Cross-engine parity probes for Gravkill — Cycle 1 closure for the
bare-shape ``Effect::ExileTargetCreature`` Rust variant.

**Bare-shape ``ExileTargetCreature`` substrate (2026-05-22).**
Gravkill ({3}{B} Instant, EoE — ``data/edge_of_eternities.json``):
"Exile target creature or Spacecraft." The parser drops the "or
Spacecraft" leg today (a separate oracle-divergence finding); the
parsed ``spell_effect`` is bare ``ExileTargetCreature``
(``effects/generic/exile.py:717`` — sugar over
``Exile(targets=(TargetSpec(IsCreature()),))``). This lane lands the
matching Rust ``Effect::ExileTargetCreature`` substrate + bridge
arms + admit-set leaf so Gravkill flips PROBED byte-equal.

The substrate that makes this slice possible:

  1. ``Effect::ExileTargetCreature`` field-free unit variant + parse
     ``"exile_target_creature"`` + ``to_pydict`` (``rust/src/cards.rs``)
     — schema parity with Python's parameterless
     ``ExileTargetCreature`` dataclass.
  2. Resolve arm in ``rust/src/state_ops_resolve.rs`` reads the
     cast-time-bound target from
     ``current_resolve_payload_target_id`` per CR 608.2b (the
     established Exorcise / Seedship payload-target swap pattern),
     re-validates "is still a battlefield Creature", exiles to
     target's owner zone, and skips DIES dispatch (bf→exile is not
     "die" per CR 700.4). Indestructible is NOT skipped — exile
     bypasses indestructible per CR 702.12c.
  3. ``state_ops_legal.rs`` ``spell_targets_satisfiable`` arm with
     ANY-creature scan, NOT controller-restricted.
  4. ``cross_engine.py`` ``exile_target_creature`` dict→Python
     bridge arm (constructs the field-free ``ExileTargetCreature()``).
  5. ``trajectory.py`` ``_python_spell_effect_to_dict`` ``_leaf`` arm
     emitting ``{"kind": "exile_target_creature"}`` — what flips
     Gravkill into the spell-card-bridge admit set (auto-grow, no
     hardcoded card list).

The Cycle 1 lane scope is bare ``ExileTargetCreature``. Cycle 2 in
the Archenemy's Charm lane wires this Effect arm through the modal
envelope (Mode 0 of "exile target creature; you draw a card and you
lose 3 life; target opponent discards a card"). Final Vengeance
(``{B}`` Sorcery, Duskmourn) ALSO emits bare ``ExileTargetCreature``
but has the additional-cost-sacrifice-creature-or-enchantment rider
the Rust engine does not yet model; the admit gate's new
rider-narrow guard correctly declines it (pinned below).

**Lane is APPEND-only** in the Rust files per the concurrent-agent
playbook; this test file is per-card-module per the
``test_exorcise_parity.py`` / ``test_drill_too_deep_parity.py``
precedent (avoids the shared ``test_parity_smoke.py`` collision).

Covered:

- Real Gravkill printing's ``spell_effect`` IS ``ExileTargetCreature()``.
- Serializer round-trip emits the bare unit-variant dict; bridge
  dict→Python arm reconstructs ``ExileTargetCreature()``.
- The card passes the ``_printing_is_bridge_simple_spell`` admit
  gate (auto-grow §2 teeth).
- Final Vengeance STAYS DECLINED via the rider-narrow guard.
- Rust resolve arm exiles a creature (synthetic-state probe; the
  None-payload fallback path).
- Rust resolve arm exiles an INDESTRUCTIBLE creature (the
  exile-vs-destroy distinction).
- Rust resolve arm silently fizzles when no creature is on the bf.
- GENUINE real-printing cross-engine byte-equal probe — the parsed
  Gravkill printing driven against a vanilla creature on the
  opponent's battlefield; both engines agree on the WHOLE field view
  post-resolve.
"""

from __future__ import annotations

import pytest


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_gravkill_spell_effect_is_exile_target_creature():
    """**Verify-first.** The live parser maps Gravkill to
    ``ExileTargetCreature()`` — a parameterless frozen dataclass
    (sugar over the generic ``Exile``). This pin freezes the parser
    SoT so a parser drift is caught here, not silently downstream
    in the cross-engine probe.

    Oracle text "exile target creature or Spacecraft" has the
    Spacecraft leg dropped by the parser today — a separate
    oracle-divergence finding tracked in the parser's coverage doc.
    The PARSED shape is bare ``ExileTargetCreature``; the bridge
    closure in this lane mirrors that parsed shape byte-equal."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.exile import ExileTargetCreature

    p = get_active_source().get_printings().get("Gravkill")
    if p is None:
        pytest.skip("Gravkill absent from active CardSource")
    assert "Instant" in p.card_types
    se = p.spell_effect
    assert type(se) is ExileTargetCreature, (
        f"Gravkill spell_effect must be exactly ExileTargetCreature "
        f"(not a subclass); got {type(se).__name__}"
    )


# -------------------------------------------------------------------
# Round-trip + admit-gate pins (the auto-grow §2 teeth).
# -------------------------------------------------------------------


def test_exile_target_creature_serializer_round_trip():
    """The trajectory reverse-serializer must emit a clean
    ``{"kind": "exile_target_creature"}`` unit dict; the dict→Python
    bridge must reconstruct ``ExileTargetCreature()``.

    A no-emit serializer would short-circuit the admit gate (the
    no-fallback-hybrid teeth). With the leaf landed and the variant
    field-free, the round-trip is byte-equal both ways."""
    from mtg_bot.effects.generic.exile import ExileTargetCreature
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = ExileTargetCreature()
    d = trajectory._python_spell_effect_to_dict(eff)
    assert d == {"kind": "exile_target_creature"}, (
        f"ExileTargetCreature reverse serializer must emit the bare "
        f"unit-variant dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert type(rebuilt) is ExileTargetCreature, (
        f"dict→Python bridge must round-trip to ExileTargetCreature; "
        f"got {type(rebuilt).__name__}"
    )


def test_gravkill_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-slice (this lane), Gravkill MUST
    pass ``_printing_is_bridge_simple_spell`` — the spell-card-bridge
    admit gate. The card has (1, 1) target_count_range with empty
    slot_kinds (Phase-1 admit shape); the spell_effect is
    covered+bridged; the serializer round-trips cleanly (the §2 teeth
    all fire positively)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Gravkill")
    if p is None:
        pytest.skip("Gravkill absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is True, (
        "Gravkill must auto-join the spell-card-bridge admit set now "
        "that its Effect is covered+bridged + round-trips"
    )
    # Pin per-tooth gates — if any one fails, debug-time message
    # points at WHICH tooth.
    assert (
        trajectory._spell_effect_is_covered_and_bridged(p) is True
    )
    assert (
        trajectory._python_spell_effect_to_dict(p.spell_effect)
        is not None
    )


def test_exile_target_creature_class_covered():
    """``ExileTargetCreature`` must be in the covered-by-rust set.

    The override ``"ExileTarget" -> "ExileTargetCreature"`` was
    already in ``RUST_TO_PYTHON_OVERRIDES`` pre-lane (mapped the
    legacy ``Effect::ExileTarget { AnyCreature }`` arm to the Python
    subclass). The new ``Effect::ExileTargetCreature`` Rust variant
    identity-maps to the same Python class — both routes contribute
    membership. Test pins that the Python class is reachable via the
    covered-set machinery (the §2 admit-gate teeth refuse to flip
    the card otherwise)."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "ExileTargetCreature" in covered, (
        "Python ExileTargetCreature class must be in the covered "
        "set (covered by Rust's Effect::ExileTargetCreature variant "
        "AND the legacy Effect::ExileTarget AnyCreature override)"
    )


def test_final_vengeance_stays_declined_via_additional_cost_rider():
    """**Defense-in-depth pin — additional-cost-sacrifice rider
    guard.** Final Vengeance ({B} Sorcery, Duskmourn) ALSO has a
    bare ``ExileTargetCreature`` spell_effect (same shape as
    Gravkill), but its
    ``additional_cost_sacrifice_creature_or_enchantment`` rider is
    NOT yet modeled on the Rust side. Admitting it would silently
    mistranslate cast-legality + post-cast state cross-engine. The
    admit gate's new rider-narrow guard at
    ``trajectory._printing_is_bridge_simple_spell`` correctly
    declines it. When the additional-cost-sacrifice channel ships
    in a future lane, this test will need to flip to admit=True."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Final Vengeance")
    if p is None:
        pytest.skip("Final Vengeance absent from active CardSource")
    # Sanity: parser maps it to the same bare ExileTargetCreature
    # shape (the §2 covered + round-trip gates would otherwise
    # produce false negatives by other means).
    from mtg_bot.effects.generic.exile import ExileTargetCreature
    assert type(p.spell_effect) is ExileTargetCreature
    # Sanity: the rider attr is set on this printing (verify-first).
    assert (
        getattr(
            p, "additional_cost_sacrifice_creature_or_enchantment",
            False,
        )
        is True
    ), (
        "Final Vengeance must carry the "
        "additional_cost_sacrifice_creature_or_enchantment rider — "
        "verify-first parser SoT pin"
    )
    # The lane-level decline pin.
    assert trajectory._printing_is_bridge_simple_spell(p) is False, (
        "Final Vengeance must STAY DECLINED — its additional-cost-"
        "sacrifice rider is not modeled cross-engine; admitting it "
        "would silently mistranslate (the §2 honest-stop discipline)"
    )


# -------------------------------------------------------------------
# Rust resolve-arm pins (synthetic state — drives the None-payload
# fallback path + the indestructible-bypass case + the empty-bf
# fizzle).
# -------------------------------------------------------------------


def _build_rust_exile_target_creature_state(
    *,
    seed_target_creature: bool = True,
    indestructible: bool = False,
):
    """Build a Rust state with a bare-ExileTargetCreature spell on
    p0's stack. When ``seed_target_creature=True`` seeds a vanilla
    2/2 Creature on p1's bf (the None-payload fallback's
    deterministic-first pick). Returns ``(rs, target_id_or_None)``."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    ZB = 2
    target_id = None
    if seed_target_creature:
        printing = {
            "name": "Test Target Creature",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        }
        if indestructible:
            printing["keywords"] = ["indestructible"]
        target_id = rs.register_and_inject_object(printing, 1, ZB)
    spell_id = rs.register_and_inject_object(
        {"name": "Test Exile Spell", "card_types": ["Instant"],
         "effects": [{"kind": "exile_target_creature"}]},
        0, 0,
    )
    rs.push_to_stack(spell_id, 0)
    return rs, target_id


def test_rust_exile_target_creature_exiles_vanilla_creature():
    """Rust pin (a): the happy path — a vanilla Creature on p1's bf
    gets exiled to p1's exile zone. None-payload synthetic-test
    fallback picks the first Creature in ETB-timestamp order across
    BOTH bfs; the only creature here is the seeded one, so the pick
    is deterministic."""
    rs, target = _build_rust_exile_target_creature_state()
    assert rs.stack_size() == 1
    rs.resolve_top_of_stack()
    assert not any(
        e["id"] == target for e in rs.battlefield_snapshot()
    ), "creature target must leave the battlefield (exiled)"
    assert any(
        e["id"] == target for e in rs.exile_snapshot(1)
    ), "exiled creature must land in its controller's exile zone"


def test_rust_exile_target_creature_exiles_indestructible_creature():
    """Rust pin (b): an indestructible creature is STILL exiled (CR
    702.12c — exile bypasses indestructible). Distinguishes from
    the destroy siblings (e.g. ``DestroyTargetCreature``) which DO
    skip indestructible. The resolve arm has no indestructible-skip;
    the ``state_ops_legal.rs::spell_targets_satisfiable`` arm also
    has no indestructible-skip (mirrors the established
    ``Effect::ExileTarget { AnyCreature }`` and ``ExorciseEffect``
    precedents)."""
    rs, target = _build_rust_exile_target_creature_state(
        indestructible=True,
    )
    rs.resolve_top_of_stack()
    assert not any(
        e["id"] == target for e in rs.battlefield_snapshot()
    ), (
        "indestructible creature MUST be exiled (exile bypasses "
        "indestructible per CR 702.12c) — distinguishes from destroy "
        "siblings that skip indestructible"
    )
    assert any(
        e["id"] == target for e in rs.exile_snapshot(1)
    ), "exiled indestructible creature must land in its exile zone"


def test_rust_exile_target_creature_silent_fizzle_no_creature():
    """Rust pin (c): with no Creature on either bf, the spell
    silently fizzles. No exception; stack drains; no exile-zone
    mutation. Mirrors Python's ``Exile.resolve`` early-return when
    the slot's IsCreature filter has no match."""
    rs, _target = _build_rust_exile_target_creature_state(
        seed_target_creature=False,
    )
    assert rs.stack_size() == 1
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve (fizzling)"
    # Both exile zones empty post-fizzle.
    assert rs.exile_snapshot(0) == []
    assert rs.exile_snapshot(1) == []


# -------------------------------------------------------------------
# Genuine real-printing cross-engine byte-equal probe.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_gravkill_parity():
    """**GENUINE real-printing cross-engine probe — Gravkill.
    PROBED-tier flip (bare ``ExileTargetCreature`` substrate).**

    Drives the **ACTUAL parsed Gravkill printing** on the Python
    side: ``get_active_source().get_printings()["Gravkill"]`` —
    which the live parser maps to a ``spell_effect`` of
    ``ExileTargetCreature()`` (verified above; the
    parser's Spacecraft-leg drop is a separate finding, not in
    scope for this lane — the cross-engine bridge mirrors the
    PARSED shape byte-equal).

    Oracle (parsed shape — Spacecraft leg dropped):
        ``{3}{B}`` Instant, ExileTargetCreature.

    **Deterministic, no RNG. Empty libraries on both engines** so
    no library reads happen during resolve.

    p0 has the genuine Gravkill; p1 has a vanilla 3/3 creature (the
    only Creature on either bf, so deterministic-first on both
    engines). The WHOLE field view is asserted byte-equal
    post-resolve."""
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
    from mtg_bot.effects.generic.exile import ExileTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Gravkill")
    if real is None:
        pytest.skip("Gravkill absent from active CardSource")
    assert "Instant" in real.card_types
    assert type(real.spell_effect) is ExileTargetCreature

    def _vanilla_creature(name, power, toughness):
        return CardPrinting(
            name=name, mana_cost_str="", mana_cost=ManaCost(generic=0),
            type_line="Creature", supertypes=(),
            card_types=("Creature",), subtypes=(),
            power=power, toughness=toughness, produces=frozenset(),
            keywords=(),
        )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 opponent 3/3 vanilla — the only Creature on either bf, so
    # deterministic-first pick on both engines.
    py_target = py.new_object(
        _vanilla_creature("Gravkill Target 3/3", 3, 3), owner_id=1,
        zone=Zone.BATTLEFIELD,
    )
    py_target.summoning_sick = False
    py.battlefield.append(py_target)
    rs_target = rs.register_and_inject_object(
        {"name": "Gravkill Target 3/3", "card_types": ["Creature"],
         "power": 3, "toughness": 3},
        1, ZB,
    )

    # Cast the genuine Gravkill on the 3/3.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_target.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    rs_spell = rs.register_and_inject_object(
        {"name": "Gravkill", "card_types": ["Instant"],
         "effects": [{"kind": "exile_target_creature"}]},
        0, 0,
    )
    rs.push_to_stack(rs_spell, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # FULL byte-equal compare. The 3/3 is exiled by both engines.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Gravkill post-resolve must be byte-equal across the WHOLE "
        f"field view on BOTH engines (bare ExileTargetCreature + "
        f"exile-to-owner-zone); diffs={diffs}"
    )
    # Observable cross-checks (defense-in-depth on top of the full
    # field byte-equality).
    assert not [o for o in py.battlefield if o.id == py_target.id], (
        "Python: 3/3 exiled by ExileTargetCreature"
    )
    assert not any(
        e["id"] == rs_target for e in rs.battlefield_snapshot()
    ), "Rust: 3/3 exiled by Effect::ExileTargetCreature (byte-equal)"
    assert any(
        o.id == py_target.id for o in py.players[1].exile
    ), "Python: exiled 3/3 in p1's exile"
    assert any(
        e["id"] == rs_target for e in rs.exile_snapshot(1)
    ), "Rust: exiled 3/3 in p1's exile (byte-equal)"
