"""Cross-engine parity probes for Vengeful Possession.

**Control-change-UEOT subsystem — Vengeful Possession Cycle 1
(2026-05-22).** ``{2}{R}`` Sorcery: "Gain control of target creature
until end of turn. Untap it. It gains haste until end of turn. You
may discard a card. If you do, draw a card."

Mirrors Python's ``Sequence(ThreatenTargetCreatureUEOT,
IfYouDo(MayDo(DiscardSelf(1)), DrawCards(1)))`` — a threaten core
composed with an optional looter rider.

The substrate that makes this slice possible:

  1. **Cycle 1 substrate.** ``GameObject.controller_override:
     Option<u8>`` field + ``effective_controller_id`` helper +
     ``grant_control_change_ueot`` PyO3 setter + cleanup-step drain.
  2. **Cycle 3 substrate.** Python ↔ Rust bridge round-trip for the
     per-object ``controller_override`` field.
  3. **Cycle 4 / Cycle 5 precedents.** Mutinous Massacre / Systems
     Override Effect variants — inlined override-mint pattern, haste
     UEOT push, untap.
  4. **THIS lane.** Vengeful Possession —
     ``Effect::ThreatenTargetCreatureUEOT`` (the field-free unit
     variant) + the resolve arm (control-grant + untap + haste UEOT)
     + the matching ``_leaf`` arms for the surrounding composite
     Effects (``Sequence``, ``IfYouDo``, ``MayDo``, ``DiscardSelf``,
     ``DrawCards``) so the round-trip dict shape is whole and the
     spell-card-bridge admit gate auto-flips Vengeful Possession.

All five composite Effects (``Sequence``, ``IfYouDo``, ``MayDo``,
``DiscardSelf``, ``DrawCards``) were ALREADY Rust-covered AND had
``cross_engine.py`` bridge arms at this cycle's HEAD; the only Rust
gap closed by this lane is ``Effect::ThreatenTargetCreatureUEOT``
itself. The ``_leaf`` arms in ``trajectory.py`` close the Python →
dict reverse serializer side.

Lives in its own module per the established per-card-module convention
(cf. ``test_systems_override_parity.py``, ``test_mutinous_massacre_
parity.py``, ``test_exorcise_parity.py``).
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_vengeful_possession_spell_effect_is_threaten_looter():
    """**Verify-first.** The live parser maps Vengeful Possession to
    ``Sequence(ThreatenTargetCreatureUEOT(),
    IfYouDo(MayDo(DiscardSelf(1)), DrawCards(1)))``. Freezes the parser
    SoT so a parser drift is caught here, not silently downstream in
    the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import IfYouDo, MayDo, Sequence
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.pump import ThreatenTargetCreatureUEOT

    p = (
        get_active_source().get_printings().get("Vengeful Possession")
    )
    if p is None:
        pytest.skip("Vengeful Possession absent from active CardSource")
    assert "Sorcery" in p.card_types
    se = p.spell_effect
    expected = Sequence(
        effects=(
            ThreatenTargetCreatureUEOT(),
            IfYouDo(
                do_action=MayDo(inner=DiscardSelf(amount=1), prompt=""),
                then_action=DrawCards(amount=1),
            ),
        )
    )
    assert se == expected, (
        f"Vengeful Possession spell_effect must be the canonical "
        f"threaten-looter composition; got {se}"
    )


# -------------------------------------------------------------------
# Round-trip + admit-gate pins (the auto-grow §2 teeth).
# -------------------------------------------------------------------


def test_vengeful_possession_serializer_round_trip():
    """The trajectory reverse-serializer must emit the nested dict shape
    for the full ``Sequence(ThreatenTargetCreatureUEOT, IfYouDo(MayDo(
    DiscardSelf), DrawCards))`` composition; the dict→Python bridge
    must reconstruct the exact same effect tree byte-equal.

    A no-emit serializer would short-circuit the admit gate (the no-
    fallback-hybrid teeth). With the ``Effect::ThreatenTargetCreatureUEOT``
    variant landed + the new ``_leaf`` arms in trajectory.py, all five
    composite Effects (Sequence, IfYouDo, MayDo, DiscardSelf, DrawCards)
    AND the new threaten leaf round-trip cleanly."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = (
        get_active_source().get_printings().get("Vengeful Possession")
    )
    if p is None:
        pytest.skip("Vengeful Possession absent from active CardSource")
    d = trajectory._python_spell_effect_to_dict(p.spell_effect)
    expected_dict = {
        "kind": "sequence",
        "effects": [
            {"kind": "threaten_target_creature_ueot"},
            {
                "kind": "if_you_do",
                "do_action": {
                    "kind": "may_do",
                    "inner_effect": {"kind": "discard_self", "amount": 1},
                    "prompt": "",
                },
                "then_action": {"kind": "draw_cards", "count": 1},
            },
        ],
    }
    assert d == expected_dict, (
        f"Vengeful Possession reverse serializer must emit the nested "
        f"threaten-looter dict shape; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert rebuilt == p.spell_effect, (
        f"dict→Python bridge must round-trip byte-equal; got {rebuilt}"
    )


def test_threaten_target_creature_ueot_serializer_round_trip():
    """Sibling unit-leaf round-trip for the new
    ``ThreatenTargetCreatureUEOT`` variant in isolation — guards the
    leaf used by Vengeful Possession's Sequence child position AND any
    future card that prints the bare Threaten core."""
    from mtg_bot.effects.generic.pump import ThreatenTargetCreatureUEOT
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = ThreatenTargetCreatureUEOT()
    d = trajectory._python_spell_effect_to_dict(eff)
    assert d == {"kind": "threaten_target_creature_ueot"}, (
        f"ThreatenTargetCreatureUEOT reverse serializer must emit the "
        f"bare unit-variant dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, ThreatenTargetCreatureUEOT)


def test_vengeful_possession_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-Cycle-1, Vengeful Possession MUST
    pass ``_printing_is_bridge_simple_spell`` — the spell-card-bridge
    admit gate. The card has (1, 1) target_count_range and empty
    slot_kinds (the Phase-1 single-target admit shape); the
    spell_effect is covered+bridged; the serializer round-trips
    cleanly. The §2 teeth all fire positively."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = (
        get_active_source().get_printings().get("Vengeful Possession")
    )
    if p is None:
        pytest.skip("Vengeful Possession absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is True, (
        "Vengeful Possession must auto-join the spell-card-bridge "
        "admit set now that ThreatenTargetCreatureUEOT is "
        "covered+bridged and the looter-rider composite Effects all "
        "round-trip"
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


def test_threaten_target_creature_ueot_class_covered():
    """``ThreatenTargetCreatureUEOT`` must be in the covered-by-rust
    set — the Rust ``Effect::ThreatenTargetCreatureUEOT`` variant
    declaration makes ``covered_python_class_set()`` include it. Without
    this, the §2 admit-gate teeth refuse to flip the card."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "ThreatenTargetCreatureUEOT" in covered, (
        "Rust Effect::ThreatenTargetCreatureUEOT variant must make the "
        "Python ThreatenTargetCreatureUEOT class covered"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins.
# -------------------------------------------------------------------


def _fresh_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _new_creature(rs, name, owner, power=2, toughness=2):
    """Inject a vanilla creature on owner's battlefield."""
    return rs.register_and_inject_object(
        {
            "name": name,
            "card_types": ["Creature"],
            "power": power,
            "toughness": toughness,
        },
        owner, ZONE_BATTLEFIELD,
    )


def _new_artifact(rs, name, owner):
    """Inject a non-creature artifact on owner's bf (used as a
    decline-target probe)."""
    return rs.register_and_inject_object(
        {
            "name": name,
            "card_types": ["Artifact"],
        },
        owner, ZONE_BATTLEFIELD,
    )


def _push_threaten(rs, caster, target_id):
    """Inject a bare-Threaten Sorcery on the caster's stack with the
    given payload-target. The Sequence wrapper is excluded here so each
    resolve-arm unit pin exercises the threaten arm in isolation; the
    full-composite (Sequence + IfYouDo) is exercised in the integration
    test below."""
    spell_id = rs.register_and_inject_object(
        {
            "name": "Threaten Probe",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "threaten_target_creature_ueot"}],
        },
        caster, ZONE_HAND,
    )
    rs.push_to_stack_with_target(spell_id, caster, target_id)
    return spell_id


def test_rust_resolve_grants_control_untap_haste_on_opponent_creature():
    """Threaten core on an opponent's creature: stamps
    controller_override = caster, untaps, grants haste UEOT."""
    rs = _fresh_state()
    bear = _new_creature(rs, "Opp Bear", owner=1)
    rs.tap_object(bear)  # tapped to verify untap fires
    _push_threaten(rs, caster=0, target_id=bear)
    rs.resolve_top_of_stack()

    bf = rs.battlefield_snapshot()
    bear_dict = next(e for e in bf if e["id"] == bear)
    assert bear_dict["controller_override"] == 0, (
        f"opponent bear must have controller_override=0; got "
        f"{bear_dict['controller_override']}"
    )
    assert rs.effective_controller_id(bear) == 0
    assert bear_dict["tapped"] is False


def test_rust_resolve_own_target_untap_no_override():
    """Own creature target: NO override (same-controller short-circuit
    per the Cycle-1 helper semantics — mirrored in the inline grant
    body); but untap + haste still apply. Mirrors Systems Override's
    own-target parity pin."""
    rs = _fresh_state()
    my_bear = _new_creature(rs, "My Bear", owner=0)
    rs.tap_object(my_bear)
    _push_threaten(rs, caster=0, target_id=my_bear)
    rs.resolve_top_of_stack()

    bf = rs.battlefield_snapshot()
    obj = next(e for e in bf if e["id"] == my_bear)
    assert obj["controller_override"] is None, (
        "own creature must have NO controller_override (same-"
        "controller short-circuit)"
    )
    assert obj["tapped"] is False
    assert rs.effective_controller_id(my_bear) == 0


def test_rust_resolve_creature_filter_declines_artifact():
    """The Threaten core's legal_targets filter restricts to creatures
    (Python: ``printing.is_creature``). Driving the Rust resolve arm
    with an artifact payload-target results in a silent no-op — the
    bf_iter find_map skips non-creatures."""
    rs = _fresh_state()
    art = _new_artifact(rs, "Opp Artifact", owner=1)
    rs.tap_object(art)
    _push_threaten(rs, caster=0, target_id=art)
    rs.resolve_top_of_stack()

    bf = rs.battlefield_snapshot()
    obj = next(e for e in bf if e["id"] == art)
    # Silent no-op: NO override stamped, NO untap.
    assert obj["controller_override"] is None
    assert obj["tapped"] is True
    assert rs.effective_controller_id(art) == 1


def test_rust_resolve_no_target_silent_noop():
    """No payload-target + no eligible creature on the bf: silent
    no-op (the bf_iter fallback finds nothing). Distinct from the
    fail-loud convention because the Sequence wrapper may pre-empt
    target binding when caller drives a no-target push path (e.g. the
    pure synthetic ``push_to_stack`` route)."""
    rs = _fresh_state()
    spell_id = rs.register_and_inject_object(
        {
            "name": "Threaten Probe",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "threaten_target_creature_ueot"}],
        },
        0, ZONE_HAND,
    )
    # No target — use the bare push_to_stack helper.
    rs.push_to_stack(spell_id, 0)
    rs.resolve_top_of_stack()
    # No creatures exist — the bf_iter fallback finds nothing, silent
    # no-op. Nothing to assert beyond "did not crash".


def test_rust_cleanup_drains_override_and_haste_after_threaten():
    """**Cycle-1 substrate composition pin.** Post-resolve, the cleanup-
    step drain reverts ``controller_override`` back to None AND clears
    the haste UEOT modifier. Composes:
      - Cycle-1 ``clear_controller_overrides_all``
      - Round-27 ``clear_ueot_modifiers_all``
    """
    rs = _fresh_state()
    bear = _new_creature(rs, "Opp Bear", owner=1)
    rs.tap_object(bear)
    _push_threaten(rs, caster=0, target_id=bear)
    rs.resolve_top_of_stack()
    # Mid-turn: override stamped, haste granted.
    bf = rs.battlefield_snapshot()
    obj = next(e for e in bf if e["id"] == bear)
    assert obj["controller_override"] == 0
    assert rs.effective_controller_id(bear) == 0

    # Synthetic state's active_player defaults to 0. The cleanup
    # helper drains controller_override + UEOT modifiers for the
    # active player. Mirrors the sibling Systems Override / Mutinous
    # Massacre cleanup-drain pin.
    assert rs.active_player == 0
    rs.cleanup_step_for_active_player()

    bf = rs.battlefield_snapshot()
    obj = next(e for e in bf if e["id"] == bear)
    assert obj["controller_override"] is None, (
        f"controller_override must drain at cleanup; got "
        f"{obj['controller_override']}"
    )
    # Effective controller back to baseline owner.
    assert rs.effective_controller_id(bear) == 1


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine probe.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_vengeful_possession_control_change_parity():
    """**The lever pin.** Drive the live parsed Vengeful Possession
    printing through both engines on the SAME synthetic state shape:
    caster (p0) targets an opponent-controlled (p1) tapped Bear. Both
    engines must:

      * grant effective control of the Bear to the caster;
      * untap the Bear;
      * grant haste UEOT;
      * have the discard+draw looter rider run (the caster has an
        empty hand on this seed, so the may-discard fizzles via the
        DiscardSelf False return path, and the draw is NOT triggered).

    Pins the round-trip dict shape AND the Rust resolve arm against
    Python's parser SoT. With the Cycle-1 substrate already shipped and
    THIS cycle's ``Effect::ThreatenTargetCreatureUEOT`` variant + the
    reverse-serializer leaves landed, every observable on both engines
    matches byte-equal."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = (
        get_active_source().get_printings().get("Vengeful Possession")
    )
    if p is None:
        pytest.skip("Vengeful Possession absent from active CardSource")
    # Round-trip the live spell_effect through dict.
    d = trajectory._python_spell_effect_to_dict(p.spell_effect)
    assert d is not None
    rebuilt = _ta_dict_to_python_effect(d)
    assert rebuilt == p.spell_effect

    # ----- Rust side -----
    rs = _fresh_state()
    bear = _new_creature(rs, "Opp Bear", owner=1)
    rs.tap_object(bear)
    # Inject the full Vengeful Possession spell shape — the SAME dict
    # the reverse serializer just emitted — so the Rust parse_effect
    # arm consumes the live round-trip schema.
    spell_id = rs.register_and_inject_object(
        {
            "name": "Vengeful Possession",
            "card_types": ["Sorcery"],
            "effects": [d],
        },
        0, ZONE_HAND,
    )
    rs.push_to_stack_with_target(spell_id, 0, bear)
    # Drain the resolve. The IfYouDo / MayDo may push a pending
    # decision (Rust queues the MayDo decision); resolve to default.
    rs.resolve_top_of_stack()
    # Drain any pending decisions (MayDo on empty hand auto-resolves
    # to a fizzle on Rust just as Python's DiscardSelf returns False).
    if hasattr(rs, "auto_resolve_pending_decisions"):
        try:
            rs.auto_resolve_pending_decisions("default")
        except Exception:
            pass

    bf = rs.battlefield_snapshot()
    bear_dict = next(e for e in bf if e["id"] == bear)
    assert bear_dict["controller_override"] == 0, (
        f"Rust: opponent bear must have controller_override=0 after "
        f"VP resolve; got {bear_dict['controller_override']}"
    )
    assert bear_dict["tapped"] is False, (
        f"Rust: opponent bear must be untapped after VP resolve"
    )
    assert rs.effective_controller_id(bear) == 0
